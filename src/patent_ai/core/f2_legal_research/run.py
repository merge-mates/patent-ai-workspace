"""F2 진입 함수 (걷는 뼈대, tasks.md m2-i3): OA 정리 결과 + F3 판단 단위 -> 법률 근거 묶음(④).

모델을 부르지 않는다. 판단 단위마다 묶음 하나:
1. 기준일 = OA 발송일 (원문 글자를 날짜로 읽음). 못 읽으면 조문을 찾지 않는다 (판이 갈려서).
2. 거절이유 조문을 그날 시행판에서 ID 조회 (`get_article`).
3. 출처 확인(코드, 무조건): 통과한 근거만 주장에 넣는다. 근거 검토(모델)는 #29라서
   주장에 review가 없고 `needs_human_review`를 단다.
4. 심사기준·판례·심결은 색인 전이라 `search_log`에 status unverified(body_missing)로 남긴다
   (못 찾음 ≠ 없음). law corpus는 실행마다 한 번만 읽는다 (`LawPool`).
주장 글은 "어느 조문이 근거인가"만 적는다. 이 사건에 적용된다는 판단은 쓰지 않는다.
"""

import logging
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from patent_ai.core.f2_legal_research.refs import ArticleRef, article_ref, parse_dispatch_date
from patent_ai.core.f2_legal_research.tools import (
    LawPool,
    check_source,
    get_article,
    search_not_indexed,
)
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.schemas.common import (
    Evidence,
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
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
    summarize_bundle_status,
    summarize_claim_status,
)
from patent_ai.core.schemas.oa_result import OAResult, Rejection
from patent_ai.retrieval.repository import ChunkRepository, PostgresChunkRepository
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)

_ALL_KINDS = [
    LegalSourceKind.STATUTE,
    LegalSourceKind.GUIDELINE,
    LegalSourceKind.PRECEDENT,
    LegalSourceKind.TRIAL,
]
_ALL_BUNDLES = "모든 판단 단위의 법률 근거 묶음 확인"


class F2Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index_version: str  # 법령 색인 판 (law corpus)
    chat_search_k: int = Field(default=3, ge=1)  # 법률 질문: 번호 없는 질문의 BM25 조문 수


class F2Input(BaseModel):
    """run_f2 도구 입력. 저장소 같은 객체는 넣지 않는다 (run_f2가 안에서 만든다)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    oa: OAResult
    units: list[JudgmentUnit]
    checked_on: date  # 확인 기준일 (코드가 오늘 날짜를 몰래 읽지 않게 입력으로 받음)
    settings: F2Settings


class F2Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    oa_id: str
    bundles: list[LegalEvidenceBundle] = Field(default_factory=list)
    status: Status  # 묶음 status 중 가장 나쁜 것


def load_f2_settings(config_dir: Path | None = None) -> F2Settings:
    """config/f2.yaml을 읽는다. 칸이 빠지면 기본값으로 때우지 않고 멈춘다."""
    path = (config_dir or REPO_ROOT / "config") / "f2.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return F2Settings.model_validate(data)
    except ValidationError as e:
        raise ModelConfigError(f"{path.name} 설정 값이 잘못됨: {e}") from e


def make_law_repo() -> ChunkRepository:
    """진짜 법령 조각 저장소 (DATABASE_URL). 테스트는 이 함수를 바꾸거나 run_f2에 repo를 넘긴다."""
    return PostgresChunkRepository.from_url()


def edition_text(chunk: Chunk) -> str | None:
    """사람이 읽는 판본: `특허법_1002_20200101 시행 2020-01-01 ~ 현행`. 시작일 모르면 None."""
    ed = chunk.edition
    if ed.status != "confirmed" or ed.effective_from is None:
        return None
    end = ed.effective_to.isoformat() if ed.effective_to else "현행"
    return f"{chunk.doc_id} 시행 {ed.effective_from.isoformat()} ~ {end}"


def _question(rej: Rejection, as_of: date | None, label: str | None) -> LegalQuestion:
    reasoning = rej.examiner_reasoning
    text = (reasoning.value or reasoning.raw_text or "").strip() or f"거절이유 {rej.no} 법률 근거"
    return LegalQuestion(
        text=text,
        source=QuestionSource.OA_REJECTION,
        as_of=as_of,
        as_of_source=AsOfSource.OA_DISPATCH_DATE if as_of else AsOfSource.NONE,
        source_kinds=_ALL_KINDS,
        article_refs=[label] if label else [],
    )


def _empty(unit, oa, question, checked_on, status, logs=(), further=()) -> LegalEvidenceBundle:
    """주장 없는 묶음. 빈 묶음에 둘 수 있는 값은 unverified·not_found_in_scope뿐이다."""
    if status.value not in (StatusValue.UNVERIFIED, StatusValue.NOT_FOUND_IN_SCOPE):
        # 충돌(같은 날 시행판 둘)은 고를 근거가 없어 확인되지 않음(ambiguous)으로 둔다
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS)
    return LegalEvidenceBundle(
        bundle_id=f"lb:{unit.unit_id}",
        unit_id=unit.unit_id,
        oa_id=oa.oa_id,
        rejection=unit.rejection,
        question=question,
        checked_on=checked_on,
        claims=[],
        further_review=list(further),
        search_log=list(logs),
        status=status,
    )


def _unverified(reason: UnverifiedReason) -> Status:
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


# 심사기준·판례·심결: 검색이 아직 없어 body_missing으로 기록만 남기는 유형 (law-idx-v3 뒤 검색)
_NOT_SEARCHED = (LegalSourceKind.GUIDELINE, LegalSourceKind.PRECEDENT, LegalSourceKind.TRIAL)


def _question_of(
    unit: JudgmentUnit, oa: OAResult
) -> tuple[Rejection | None, date | None, ArticleRef | None, LegalQuestion]:
    """판단 단위 -> (거절이유, 기준일, 조문, 질문). 묶음을 만드는 모든 길이 이 하나를 쓴다."""
    rej = next((r for r in oa.rejections if r.no == unit.rejection), None)
    if rej is None:
        # F3 단위가 가리키는 거절이유가 OA에 없으면 앞 입력이 어긋난 것
        logger.warning("run_f2 %s: 거절이유 %d가 OA에 없음", oa.oa_id, unit.rejection)
        q = LegalQuestion(
            text=f"거절이유 {unit.rejection} 법률 근거",
            source=QuestionSource.OA_REJECTION,
            as_of_source=AsOfSource.NONE,
            source_kinds=_ALL_KINDS,
        )
        return None, None, None, q
    nd = oa.notice_date
    as_of = parse_dispatch_date(nd.raw_text) if nd.status.value == StatusValue.CONFIRMED else None
    ref = article_ref(rej.article.value)
    return rej, as_of, ref, _question(rej, as_of, ref.label if ref else None)


def _bundle(unit: JudgmentUnit, inp: F2Input, pool: LawPool) -> LegalEvidenceBundle:
    oa, checked_on = inp.oa, inp.checked_on
    rej, as_of, ref, question = _question_of(unit, oa)
    if rej is None:
        return _empty(
            unit, oa, question, checked_on, _unverified(UnverifiedReason.INPUT_UNVERIFIED)
        )
    if as_of is None or ref is None:
        # 기준일을 모르면 판이 갈려 조문을 고를 수 없다. 사람이 날짜를 확인해야 한다
        why = "발송일" if as_of is None else "조문"
        logger.warning("run_f2 %s: %s을 못 읽어 %s 조문을 찾지 않음", oa.oa_id, why, unit.unit_id)
        return _empty(
            unit, oa, question, checked_on, _unverified(UnverifiedReason.INPUT_UNVERIFIED)
        )

    found = get_article(pool, ref, as_of)
    logs = [found.log, *(search_not_indexed(pool, kind, as_of) for kind in _NOT_SEARCHED)]
    if found.chunk is None:
        # 같은 날 시행판이 둘이면 고르지 않고, 겹친 조각을 사람이 볼 수 있게 남긴다
        further = [
            FurtherReview(
                chunk_id=c.chunk_id,
                why=FurtherReviewWhy.OTHER_EDITION,
                note=f"{ref.label}: 기준일 {as_of.isoformat()}에 시행판이 둘 이상 (판본 확인 필요)",
                index_version=c.index_version,
            )
            for c in found.conflicts
        ]
        return _empty(unit, oa, question, checked_on, found.status, logs, further)

    chunk = found.chunk
    evidence = Evidence(
        document_id=chunk.doc_id,
        location=chunk.location.label,
        raw_text=chunk.text,
        edition=edition_text(chunk),
        checked_on=checked_on,
        chunk_id=chunk.chunk_id,
        index_version=chunk.index_version,
    )
    # 출처 확인: 색인에 있고, 글이 그대로이고, 기준일 판인 근거만 쓴다 (없는 출처 0건)
    if not check_source(pool, evidence.chunk_id, evidence.raw_text, as_of):
        logger.warning("run_f2 %s: %s 근거가 출처 확인에서 빠짐", oa.oa_id, chunk.chunk_id)
        return _empty(
            unit, oa, question, checked_on, _unverified(UnverifiedReason.EVIDENCE_REJECTED), logs
        )
    source = LegalSource(
        source_kind=LegalSourceKind.STATUTE,
        identifier=ref.label,
        evidence=evidence,
        status=found.status,
    )
    claim = LegalClaim(
        no=1,
        text=f"거절이유 근거 조문: {ref.label} (OA 발송일 {as_of.isoformat()} 시행판)",
        sources=[source],
        status=summarize_claim_status([source]),
        # 근거 검토(모델)를 아직 하지 않았다: 사람이 봐야 한다 (#29)
        flags=[Flag.NEEDS_HUMAN_REVIEW],
    )
    return LegalEvidenceBundle(
        bundle_id=f"lb:{unit.unit_id}",
        unit_id=unit.unit_id,
        oa_id=oa.oa_id,
        rejection=unit.rejection,
        question=question,
        checked_on=checked_on,
        claims=[claim],
        search_log=logs,
        status=summarize_bundle_status([claim]),
    )


def _missing_index(unit: JudgmentUnit, inp: F2Input, status: Status) -> LegalEvidenceBundle:
    """색인이 없을 때의 묶음: 질문은 남기고 주장은 비운다."""
    *_, question = _question_of(unit, inp.oa)
    return _empty(unit, inp.oa, question, inp.checked_on, status)


def run_f2(inp: F2Input, *, repo: ChunkRepository | None = None) -> F2Result:
    """판단 단위마다 법률 근거 묶음 하나를 만든다. repo가 없으면 make_law_repo()."""
    if not inp.units:
        logger.warning("run_f2 %s: 판단 단위가 없음 (만든 묶음 0개)", inp.oa.oa_id)
        return F2Result(oa_id=inp.oa.oa_id, status=_unverified(UnverifiedReason.INPUT_UNVERIFIED))
    repo = repo if repo is not None else make_law_repo()
    iv = inp.settings.index_version
    if not repo.has_index_version("law", iv):
        # 색인이 없어 못 본 것을 "조회 범위 내 없음"으로 내지 않는다 (못 찾음 ≠ 없음)
        logger.warning("run_f2 %s: 법령 색인 %s이 저장소에 없음", inp.oa.oa_id, iv)
        missing = _unverified(UnverifiedReason.BODY_MISSING)
        bundles = [_missing_index(u, inp, missing) for u in inp.units]
        return F2Result(oa_id=inp.oa.oa_id, bundles=bundles, status=missing)

    # law corpus를 실행마다 한 번만 읽는다 (도구마다 다시 읽지 않게, #222 리뷰)
    pool = LawPool.load(repo, iv)
    bundles = [_bundle(u, inp, pool) for u in inp.units]
    return F2Result(
        oa_id=inp.oa.oa_id,
        bundles=bundles,
        status=worst_status([b.status for b in bundles], _ALL_BUNDLES),
    )
