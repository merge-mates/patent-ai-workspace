"""F2 법률 질문 탭 (m3-i2-29a): 사용자 질문 하나 -> 출처 확인을 지난 조문 근거 묶음(④).

모델을 부르지 않는다 (design 2절 1·3·4단계를 질문에 적용):
1. `next_question`: 요청 + 앞 질문 -> 질문. 빠진 조건(시점·자료 유형)은 앞 질문에서 물려받는다.
2. `answer_question`: 조문을 찾고(번호가 있으면 ID 조회, 없으면 BM25), 출처 확인을 지난 근거만
   주장에 넣는다. 심사기준·판례·심결은 색인 전이라 body_missing으로 기록만 한다.
주장 글은 "어느 조문을 찾았나"만 적는다. 이 사건에 적용된다는 판단은 쓰지 않는다.
"""

import logging
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from patent_ai.core.f2_legal_research.refs import ArticleRef, article_refs_in_text
from patent_ai.core.f2_legal_research.run import edition_text
from patent_ai.core.f2_legal_research.tools import (
    LawPool,
    check_source,
    get_article,
    law_of,
    search_article,
    search_not_indexed,
)
from patent_ai.core.schemas.common import (
    Evidence,
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.legal_evidence import (
    AsOfSource,
    FurtherReview,
    FurtherReviewWhy,
    LegalClaim,
    LegalEvidenceBundle,
    LegalQuestion,
    LegalSource,
    LegalSourceKind,
    QuestionSource,
    SearchLogEntry,
    summarize_bundle_status,
    summarize_claim_status,
)
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)

ALL_KINDS = [
    LegalSourceKind.STATUTE,
    LegalSourceKind.GUIDELINE,
    LegalSourceKind.PRECEDENT,
    LegalSourceKind.TRIAL,
]
_NOT_SEARCHED = (LegalSourceKind.GUIDELINE, LegalSourceKind.PRECEDENT, LegalSourceKind.TRIAL)


class ChatAsk(BaseModel):
    """질문 요청 본문. as_of·source_kinds는 "빠짐"과 값을 구분한다 (`model_fields_set`).

    - as_of 빠짐 = 앞 질문 물려받기, null = 현행으로 덮기
    - source_kinds 빠짐 = 물려받기, `[]` = 전부
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    as_of: date | None = None
    source_kinds: list[LegalSourceKind] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _글이_있어야_한다(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문 글이 비어 있음")
        return v


def next_question(prev: LegalQuestion | None, ask: ChatAsk) -> tuple[LegalQuestion, bool]:
    """(질문, scope_changed). 앞 질문과 시점 또는 자료 유형(집합)이 다르면 scope_changed."""
    given = ask.model_fields_set
    # 시점: 빠지면 앞 질문 것, 앞 질문도 없으면 현행(None)
    as_of = ask.as_of if "as_of" in given else (prev.as_of if prev else None)
    # 자료 유형: 빠지면 앞 질문 것, `[]`이면 전부. 중복은 순서를 지키며 합친다
    if "source_kinds" in given:
        kinds = list(dict.fromkeys(ask.source_kinds)) or list(ALL_KINDS)
    else:
        kinds = list(prev.source_kinds) if prev else list(ALL_KINDS)
    question = LegalQuestion(
        text=ask.text.strip(),
        source=QuestionSource.USER_QUESTION,
        as_of=as_of,
        as_of_source=AsOfSource.USER_CONDITION if as_of else AsOfSource.NONE,
        source_kinds=kinds,
        article_refs=[r.label for r in article_refs_in_text(ask.text)],
    )
    changed = prev is not None and (as_of != prev.as_of or set(kinds) != set(prev.source_kinds))
    return question, changed


def _claim_text(label: str, edition: str, by_search: bool, search_k: int) -> str:
    """주장 글: 번호로 읽은 조문과 검색으로 찾은 조문을 구분한다. 사건 적용 판단은 쓰지 않는다."""
    if by_search:
        return f"질문 글로 검색한 조문 (BM25 상위 {search_k}): {label} ({edition})"
    return f"질문에서 찾은 조문: {label} ({edition})"


def _source_of(chunk: Chunk, label: str, as_of: date, checked_on: date, pool: LawPool):
    """조각 -> 근거(출처 확인에서 빠지면 None). 출처 확인은 무조건 도는 코드 단계다."""
    evidence = Evidence(
        document_id=chunk.doc_id,
        location=chunk.location.label,
        raw_text=chunk.text,
        edition=edition_text(chunk),
        checked_on=checked_on,
        chunk_id=chunk.chunk_id,
        index_version=chunk.index_version,
    )
    if not check_source(pool, evidence.chunk_id, evidence.raw_text, as_of):
        return None
    status = Status(
        value=StatusValue.CONFIRMED,
        checked=f"{label} {chunk.edition.label or chunk.doc_id} 판본·위치 확인",
    )
    return LegalSource(
        source_kind=LegalSourceKind.STATUTE, identifier=label, evidence=evidence, status=status
    )


def _empty_status(statuses: list[Status], skipped: int, scope: str) -> Status:
    """주장이 0개일 때의 묶음 status (못 찾음 != 없음)."""
    if skipped > 0:
        # 판본을 몰라 뺀 조각이 있으면 "없음"이 아니다
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.EDITION_UNKNOWN)
    for s in statuses:
        if s.value == StatusValue.UNVERIFIED:
            return s
    if any(s.value == StatusValue.CONFLICT for s in statuses):
        # 같은 날 시행판이 둘: 고를 근거가 없다
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS)
    if statuses and all(s.value == StatusValue.NOT_FOUND_IN_SCOPE for s in statuses):
        return Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
    # 법령을 찾지 않았거나 이유를 알 수 없음: 확인되지 않음
    return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)


def _before_earliest(pool: LawPool, as_of: date) -> bool:
    """기준일이 법령 조문 조각의 가장 이른 effective_from보다 앞서는가 (시작일 모름은 뺀다)."""
    starts = [
        c.edition.effective_from
        for c in pool.chunks
        if c.chunk_kind == "article" and c.edition.effective_from is not None
    ]
    return bool(starts) and as_of < min(starts)


def _statute_candidates(
    question: LegalQuestion,
    refs: list[ArticleRef],
    as_of: date,
    pool: LawPool,
    searcher: Searcher,
    search_k: int,
):
    """법령 후보 찾기 -> (후보 [(라벨, 조각)], 기록, 못 찾은 이유들, 판본 몰라 뺀 수, 범위 글)."""
    found: list[tuple[str, Chunk]] = []
    logs: list[SearchLogEntry] = []
    statuses: list[Status] = []
    skipped = 0
    if refs:
        # 글에 조문 번호가 있으면 그 조문을 ID로 조회한다
        for ref in refs:
            got = get_article(pool, ref, as_of)
            logs.append(got.log)
            skipped += got.log.skipped_unverified_edition
            if got.chunk is not None:
                found.append((ref.label, got.chunk))
            else:
                statuses.append(got.status)
        labels = ", ".join(r.label for r in refs)
        scope = f"{pool.index_version} 법령 조문 {labels}, 모든 판 (기준일 {as_of.isoformat()})"
        return found, logs, statuses, skipped, scope
    # 번호가 없으면 질문 글로 BM25 검색
    res = search_article(searcher, question.text, as_of, search_k)
    skipped = res.skipped_unverified_edition
    scope = f"{pool.index_version} 법령 조문 BM25 검색 (기준일 {as_of.isoformat()})"
    if res.hits:
        status = None
        for h in res.hits:
            found.append((f"{law_of(h.doc_id) or h.doc_id} {h.location.label}", h))
    elif res.status == "unverified":
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason(res.status_reason))
        statuses.append(status)
    elif _before_earliest(pool, as_of):
        # 기준일이 이 판 법령의 가장 이른 시행일보다 앞: 그때 판이 색인에 없다 (없음이 아니다)
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.EDITION_UNKNOWN)
        statuses.append(status)
    else:
        status = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
        statuses.append(status)
    logs.append(
        SearchLogEntry(
            source_kind=LegalSourceKind.STATUTE,
            index_version=pool.index_version,
            as_of=as_of,
            queries=1,
            hits=len(res.hits),
            skipped_unverified_edition=skipped,
            status=status,
        )
    )
    return found, logs, statuses, skipped, scope


def answer_question(
    question: LegalQuestion,
    *,
    bundle_id: str,
    pool: LawPool,
    searcher: Searcher,
    checked_on: date,
    prior_evidence: list[str],
    search_k: int,
) -> LegalEvidenceBundle:
    """질문 하나 -> 법률 근거 묶음. 검색 기준일 = 질문 시점, 없으면 확인 기준일 (design 4절)."""
    as_of = question.as_of or checked_on
    claims: list[LegalClaim] = []
    logs: list[SearchLogEntry] = []
    statuses: list[Status] = []
    skipped, scope = 0, f"{pool.index_version} 법령 (찾지 않음)"
    refs: list[ArticleRef] = []

    # STATUTE를 고른 때만 법령을 찾는다
    if LegalSourceKind.STATUTE in question.source_kinds:
        refs = article_refs_in_text(question.text)
        found, logs, statuses, skipped, scope = _statute_candidates(
            question, refs, as_of, pool, searcher, search_k
        )
        for label, chunk in found:
            # 출처 확인을 지난 근거만 주장에 넣는다 (없는 출처 0건)
            source = _source_of(chunk, label, as_of, checked_on, pool)
            if source is None:
                logger.warning(
                    "법률 질문 %s: %s 근거가 출처 확인에서 빠짐", bundle_id, chunk.chunk_id
                )
                statuses.append(
                    Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.EVIDENCE_REJECTED)
                )
                continue
            claims.append(
                LegalClaim(
                    no=len(claims) + 1,
                    text=_claim_text(
                        label,
                        source.evidence.edition or chunk.doc_id,
                        by_search=not refs,
                        search_k=search_k,
                    ),
                    sources=[source],
                    status=summarize_claim_status([source]),
                    # 근거 검토(모델)는 29b: 지금은 사람이 봐야 한다
                    flags=[Flag.NEEDS_HUMAN_REVIEW],
                )
            )

    # 심사기준·판례·심결: 아직 검색이 없어 body_missing 기록만 (못 찾음 != 없음)
    logs += [
        search_not_indexed(pool, kind, as_of)
        for kind in _NOT_SEARCHED
        if kind in question.source_kinds
    ]
    used = {c.sources[0].evidence.chunk_id for c in claims}
    in_force = {c.chunk_id for c in pool.in_force(as_of)}
    known = {c.chunk_id: c for c in pool.chunks}
    further: list[FurtherReview] = []
    for cid in dict.fromkeys(prior_evidence):
        if cid in used or cid in in_force:
            continue
        if cid not in known:
            logger.warning("법률 질문 %s: 앞 답의 조각 %s가 색인에 없음", bundle_id, cid)
            continue
        # 앞 답의 조각이 바뀐 시점의 시행판이 아니다: 쓰지 않고 사람이 볼 것으로만 남긴다
        further.append(
            FurtherReview(
                chunk_id=cid,
                why=FurtherReviewWhy.EDITION_OUT_OF_SCOPE,
                note=f"앞 답의 근거. 기준일 {as_of.isoformat()}의 시행판이 아님",
                index_version=known[cid].index_version,
            )
        )

    if claims:
        status = summarize_bundle_status(claims)
    else:
        logger.warning("법률 질문 %s: 주장 0개 (근거 0개 묶음)", bundle_id)
        status = _empty_status(statuses, skipped, scope)
    return LegalEvidenceBundle(
        bundle_id=bundle_id,
        question=question,
        checked_on=checked_on,
        claims=claims,
        further_review=further,
        search_log=logs,
        status=status,
    )
