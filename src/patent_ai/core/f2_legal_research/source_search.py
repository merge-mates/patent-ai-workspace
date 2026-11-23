"""F2 심사기준·판례·심결 검색 (design 2절 3단계, #24 24d task-d3). 모두 코드, 모델을 부르지 않는다.

- 검색은 BM25 한 가지다 (law-idx-v3에는 벡터가 없다). 값은 `config/f2.yaml` (법률 질문과 같이 쓴다).
- 심사기준은 기준일에 시행 중인 판만 본다. 그 판이 없으면(가장 이른 판 앞, 판 사이 빈 기간)
  "없음"이 아니라 `unverified(edition_unknown)`이다 (못 찾음 ≠ 없음).
- 판례·심결은 선고일이 기준일 이전인 것만 본다. 요지/전문(`text_kind`)과 판단/당사자(`speaker`)를
  근거 후보에 그대로 남긴다. 기준일을 모르면 미래 판결이 섞일 수 있어 검색하지 않는다.
- 걸린 조각은 근거 '후보'일 뿐이다. 주장으로 올리는 것은 근거 검토(#29) 몫.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from patent_ai.core.f2_legal_research.tools import CASE_KINDS, CORPUS, LawPool, check_source
from patent_ai.core.schemas.common import Evidence, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import (
    FurtherReview,
    FurtherReviewWhy,
    LegalSource,
    LegalSourceKind,
    SearchLogEntry,
    Speaker,
    TextKind,
)
from patent_ai.retrieval.contract import Searcher, get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import SearchHit, SearchResult, SourceKind

logger = logging.getLogger(__name__)

# 자료 유형 -> 색인의 source_kind
_SOURCE_KIND: dict[LegalSourceKind, SourceKind] = {
    LegalSourceKind.GUIDELINE: "guideline",
    LegalSourceKind.PRECEDENT: "precedent",
    LegalSourceKind.TRIAL: "trial",
}


@dataclass(frozen=True)
class SourceSearch:
    """자료 유형 하나를 찾은 결과: 기록(search_log)과 근거 후보."""

    log: SearchLogEntry
    sources: tuple[LegalSource, ...] = field(default_factory=tuple)


def build_searcher(pool: LawPool, tokenizer: str, bm25: dict[str, str | float | bool]) -> Searcher:
    """pool 조각 위에 BM25 검색기를 만든다 (DB를 다시 읽지 않는다)."""
    repo = InMemoryChunkRepository({CORPUS: list(pool.chunks)})
    return get_searcher(
        "bm25",
        repo,
        {
            "index_version": pool.index_version,
            "tokenizer": tokenizer,
            "bm25": dict(bm25),
        },
    )


def _to_source(hit: SearchHit, kind: LegalSourceKind, checked_on: date) -> LegalSource:
    c = hit
    ed = c.edition
    edition = None
    if ed.status == "confirmed" and ed.effective_from is not None:
        end = ed.effective_to.isoformat() if ed.effective_to else "현행"
        edition = f"{c.doc_id} 시행 {ed.effective_from.isoformat()} ~ {end}"
    evidence = Evidence(
        document_id=c.doc_id,
        location=c.location.label,
        raw_text=c.text,
        edition=edition,
        checked_on=checked_on,
        chunk_id=c.chunk_id,
        index_version=c.index_version,
    )
    status = Status(value=StatusValue.CONFIRMED, checked=f"{c.doc_id} {c.location.label} 위치 확인")
    if kind == LegalSourceKind.GUIDELINE:
        return LegalSource(
            source_kind=kind, identifier=c.location.label, evidence=evidence, status=status
        )
    return LegalSource(
        source_kind=kind,
        identifier=c.doc_id,
        evidence=evidence,
        status=status,
        text_kind=TextKind.SUMMARY if c.chunk_kind == "judgment_summary" else TextKind.FULL,
        speaker=Speaker(c.speaker or "unknown"),
        decided_on=c.decided_on,
        court=(c.attrs or {}).get("법원명"),
    )


def _unverified(reason: UnverifiedReason) -> Status:
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def _entry(kind, pool, as_of, queries, hits, status, res: SearchResult | None = None):
    return SearchLogEntry(
        source_kind=kind,
        index_version=pool.index_version,
        as_of=as_of,
        queries=queries,
        hits=hits,
        skipped_unverified_edition=res.skipped_unverified_edition if res else 0,
        skipped_unknown_date=res.skipped_unknown_date if res else 0,
        status=status,
    )


def _finish(kind, pool, as_of, res: SearchResult, scope: str, checked_on: date) -> SourceSearch:
    if not res.hits:
        if res.status == "unverified":
            reason = UnverifiedReason(res.status_reason)
            # 그 유형 조각이 없어 찾을 것이 없었다: 질의 0번으로 기록 (전과 같음)
            logger.warning("%s 조각이 색인 %s에 없음 (확인되지 않음)", kind, pool.index_version)
            return SourceSearch(_entry(kind, pool, as_of, 0, 0, _unverified(reason), res))
        if res.skipped_unknown_date or res.skipped_unverified_edition:
            # 날짜·판본을 몰라 건너뛴 조각이 있다: 그 안에 있을 수 있어 "없음"이 아니다 (design 2절)
            logger.warning(
                "%s 0개, 날짜 모름 %d개·판본 모름 %d개를 건너뜀 (확인되지 않음)",
                kind, res.skipped_unknown_date, res.skipped_unverified_edition,
            )  # fmt: skip
            reason = UnverifiedReason.EDITION_UNKNOWN
            return SourceSearch(_entry(kind, pool, as_of, 1, 0, _unverified(reason), res))
        status = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
        return SourceSearch(_entry(kind, pool, as_of, 1, 0, status, res))
    # 출처 확인(무조건 도는 코드 단계): 색인에 있고 글이 그대로이고 기준일에 맞는 것만 남긴다
    passed = [h for h in res.hits if check_source(pool, h.chunk_id, h.text, as_of)]
    for h in res.hits:
        if h not in passed:
            logger.warning("%s %s 후보가 출처 확인에서 빠짐", kind, h.chunk_id)
    if not passed:
        reason = UnverifiedReason.EVIDENCE_REJECTED
        return SourceSearch(_entry(kind, pool, as_of, 1, 0, _unverified(reason), res))
    sources = tuple(_to_source(h, kind, checked_on) for h in passed)
    status = Status(value=StatusValue.CONFIRMED, checked=f"{scope} BM25 검색 {len(sources)}건")
    return SourceSearch(_entry(kind, pool, as_of, 1, len(sources), status, res), sources)


def search_guideline(
    searcher: Searcher, pool: LawPool, query: str, as_of: date | None, k: int,
    checked_on: date,
) -> SourceSearch:  # fmt: skip
    """심사기준: 기준일에 시행 중인 판의 조각만 BM25로 찾는다."""
    kind = LegalSourceKind.GUIDELINE
    if as_of is None:
        logger.warning("심사기준: 기준일을 몰라 검색하지 않음")
        return SourceSearch(
            _entry(kind, pool, None, 0, 0, _unverified(UnverifiedReason.INPUT_UNVERIFIED))
        )
    mine = [c for c in pool.chunks if c.chunk_kind == "guideline"]
    if not mine:
        logger.warning("심사기준 조각이 색인 %s에 없음 (확인되지 않음)", pool.index_version)
        return SourceSearch(
            _entry(kind, pool, as_of, 0, 0, _unverified(UnverifiedReason.BODY_MISSING))
        )
    if not any(c.chunk_kind == "guideline" for c in pool.in_force(as_of)):
        # 기준일 판이 색인에 없다: 그날 글을 모를 뿐 없는 것이 아니다
        logger.warning("심사기준: %s에 시행 중인 판이 색인에 없음 (확인되지 않음)", as_of)
        return SourceSearch(
            _entry(kind, pool, as_of, 0, 0, _unverified(UnverifiedReason.EDITION_UNKNOWN))
        )
    res = searcher.search(query, CORPUS, "bm25", k, as_of=as_of, chunk_kinds=["guideline"])
    scope = f"{pool.index_version} 심사기준 (기준일 {as_of.isoformat()})"
    return _finish(kind, pool, as_of, res, scope, checked_on)


def search_cases(
    searcher: Searcher, pool: LawPool, kind: LegalSourceKind, query: str, as_of: date | None,
    k: int, checked_on: date,
) -> SourceSearch:  # fmt: skip
    """판례·심결: 선고일(심결일)이 기준일 이전인 조각만 BM25로 찾는다."""
    if as_of is None:
        # 기준일 없이 찾으면 OA 뒤의 판결이 섞인다
        logger.warning("%s: 기준일을 몰라 검색하지 않음", kind)
        return SourceSearch(
            _entry(kind, pool, None, 0, 0, _unverified(UnverifiedReason.INPUT_UNVERIFIED))
        )
    res = searcher.search(
        query, CORPUS, "bm25", k, as_of=as_of, chunk_kinds=CASE_KINDS,
        source_kinds=[_SOURCE_KIND[kind]], decided_on_or_before=as_of,
    )  # fmt: skip
    scope = f"{pool.index_version} {kind.value} (선고일 {as_of.isoformat()} 이전)"
    return _finish(kind, pool, as_of, res, scope, checked_on)


def search_sources(
    pool: LawPool, searcher: Searcher, query: str, as_of: date | None, k: int,
    checked_on: date, kinds: Sequence[LegalSourceKind] = tuple(_SOURCE_KIND),
) -> list[SourceSearch]:  # fmt: skip
    """심사기준·판례·심결을 차례로 찾는다. kinds에 든 유형만 (법령은 여기서 찾지 않는다)."""
    out = []
    for kind in _SOURCE_KIND:
        if kind not in kinds:
            continue
        if kind == LegalSourceKind.GUIDELINE:
            out.append(search_guideline(searcher, pool, query, as_of, k, checked_on))
        else:
            out.append(search_cases(searcher, pool, kind, query, as_of, k, checked_on))
    return out


def candidate_reviews(found: list[SourceSearch]) -> list[FurtherReview]:
    """걸린 근거 후보를 묶음의 '더 볼 것'으로 옮긴다 (주장으로 올리는 것은 근거 검토 #29 몫).

    요지/전문과 판단/당사자를 note에 남겨 사람이 어느 글인지 바로 안다. 원문·위치·판본은 source에.
    """
    out = []
    for r in found:
        for s in r.sources:
            ev = s.evidence
            if s.text_kind is not None and s.speaker is not None:
                what = f"{s.text_kind.value} · {s.speaker.value}"
            else:
                what = "심사기준"
            out.append(
                FurtherReview(
                    chunk_id=ev.chunk_id or "",
                    why=FurtherReviewWhy.NOT_USED_CANDIDATE,
                    note=f"{s.source_kind.value} {s.identifier} ({what}): 근거 검토 전 후보",
                    index_version=ev.index_version,
                    source=s,
                )
            )
    return out
