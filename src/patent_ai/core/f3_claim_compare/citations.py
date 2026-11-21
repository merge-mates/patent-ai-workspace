"""OA 인용문헌 -> 색인 doc_id와 대비 여부 (ComparedCitation).

번호·나라는 F1이 정한 값을 그대로 쓴다 (새로 정규화하지 않는다).
한국 문헌은 번호 값이 색인 doc_id다. 대비하지 않는 문헌은 버리지 않고 이유와 상태를 남긴다.
공개(A)·등록(B)이 달라도 번호를 바꿔 다시 찾지 않는다.
"""

import logging

from pydantic import BaseModel, ConfigDict

from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import ComparedCitation
from patent_ai.core.schemas.oa_result import Citation, Rejection
from patent_ai.retrieval.repository import ChunkRepository

logger = logging.getLogger(__name__)


class ResolvedCitation(BaseModel):
    """인용문헌 하나를 색인과 맞춘 결과."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str  # D1, D2…
    doc_id: str | None  # 색인 문헌 ID (번호를 못 읽었으면 None)
    chunk_count: int  # 색인에 있는 그 문헌 조각 수
    compared: ComparedCitation
    held_task: HeldTask | None = None  # 본문을 올려 주면 이어서 할 작업


def _skipped(c: Citation, why: str, reason: UnverifiedReason) -> ComparedCitation:
    return ComparedCitation(
        label=c.label,
        number=_shown_number(c),
        compared=False,
        skipped_reason=why,
        skipped_status=Status(value=StatusValue.UNVERIFIED, reason=reason),
    )


def _shown_number(c: Citation) -> str:
    """화면에 보일 번호: 키 꼴 값, 없으면 원문 표기."""
    return c.number.value or c.number.raw_text or "번호 확인되지 않음"


def _resolve(
    c: Citation, oa_id: str, repo: ChunkRepository, index_version: str
) -> ResolvedCitation:
    country = c.country.value
    # 1) 지원 안 하는 나라: 찾지 않는다. 올려 달라고도 하지 않는다 (직접 확인)
    if country is not None and not c.country_supported:
        why = f"지원 안 하는 나라 ({country}) · 직접 확인"
        skipped = _skipped(c, why, UnverifiedReason.LOOKUP_FAILED)
        return ResolvedCitation(label=c.label, doc_id=None, chunk_count=0, compared=skipped)
    # 2) 번호나 나라를 못 정함: 어느 문헌인지 몰라 찾지 않는다
    if c.number.value is None or country is None:
        why = "인용문헌 번호·나라를 확인하지 못함 · 직접 확인"
        skipped = _skipped(c, why, UnverifiedReason.AMBIGUOUS)
        return ResolvedCitation(label=c.label, doc_id=None, chunk_count=0, compared=skipped)
    # 3) 색인에 조각이 없음 (미국 문헌은 지금 색인이 건너뛰어 늘 여기로 온다)
    doc_id = c.number.value
    count = repo.count_chunks("cite", index_version, [doc_id])
    if count == 0:
        skipped = _skipped(c, "본문 미확보 · 올려 주면 대비", UnverifiedReason.BODY_MISSING)
        held = HeldTask(
            task=f"f3_compare:{oa_id}:{c.label}", waiting_for=f"{c.label} 본문 (올려 주면 대비)"
        )
        return ResolvedCitation(
            label=c.label, doc_id=doc_id, chunk_count=0, compared=skipped, held_task=held
        )
    compared = ComparedCitation(label=c.label, number=doc_id, compared=True)
    return ResolvedCitation(label=c.label, doc_id=doc_id, chunk_count=count, compared=compared)


def resolve_citations(
    rejection: Rejection, oa_id: str, repo: ChunkRepository, index_version: str
) -> list[ResolvedCitation]:
    """거절이유의 인용문헌을 OA 순서대로 색인과 맞춘다. 같은 라벨은 한 번만."""
    out: list[ResolvedCitation] = []
    seen: set[str] = set()
    for c in rejection.citations:
        if c.label in seen:
            continue
        seen.add(c.label)
        out.append(_resolve(c, oa_id, repo, index_version))
    skipped = [r.label for r in out if not r.compared.compared]
    if skipped:
        logger.warning(
            "resolve_citations 거절이유 %d: 대비하지 않는 인용 %s", rejection.no, skipped
        )
    return out
