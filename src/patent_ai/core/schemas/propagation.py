"""상태 전파와 검토할 사항 모으기. 규칙은 docs/data-model.md 3절 규칙 1·2."""

import logging
import re

from patent_ai.core.schemas.case_materials import (
    CaseDocument,
    CaseMaterials,
    ReviewItem,
    ReviewKind,
)
from patent_ai.core.schemas.common import (
    ExtractedValue,
    Flag,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.oa_result import Citation, ClaimRow, OAResult, Rejection

# ReviewItem·ReviewKind는 case_materials.py로 옮겼고(순환 import 방지) 여기서 다시 내보낸다
__all__ = [
    "ReviewItem",
    "ReviewKind",
    "collect_review_items",
    "document_review_items",
    "finalize_case_materials",
    "mark_recheck",
    "propagate",
    "sort_review_items",
]

logger = logging.getLogger(__name__)


def propagate(depends_on: list[Status]) -> Status:
    """기대는 입력의 status로 이 결과의 status를 정한다.

    입력이 모두 confirmed여야 confirmed. 하나라도 아니면 unverified(input_unverified).
    기대는 입력이 없으면 영향 없음으로 보고 confirmed.
    """
    if all(s.value == StatusValue.CONFIRMED for s in depends_on):
        return Status(
            value=StatusValue.CONFIRMED,
            checked=f"기대는 입력 {len(depends_on)}개 확인됨",
        )
    return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)


def mark_recheck[R: ResultBase](result: R, reason: str) -> R:
    """다시 확인할 표시를 단 새 결과를 돌려준다. status는 그대로, 원본도 그대로."""
    return result.model_copy(update={"needs_recheck": True, "recheck_reason": reason})


def _text(v: ExtractedValue) -> str:
    """칸의 사람이 읽는 글자: 값이 있으면 값, 없으면 원문 글자."""
    if v.value is not None:
        return str(v.value)
    return v.raw_text or "알 수 없음"


def _field_item(v: ExtractedValue | ClaimRow, target: str, label: str) -> list[ReviewItem]:
    """필드(ExtractedValue) 하나: unverified·conflict면 그 필드 경로에서 한 줄."""
    if v.status.value == StatusValue.UNVERIFIED:
        return [
            ReviewItem(kind="unverified", target=target, label=label, reason=str(v.status.reason))
        ]
    if v.status.value == StatusValue.CONFLICT:
        return [ReviewItem(kind="conflict", target=target, label=label, reason="값이 서로 충돌")]
    return []


def _flag_items(flags: list[Flag], target: str, label: str, flag_reason: dict) -> list[ReviewItem]:
    return [
        ReviewItem(
            kind=f.value,
            target=target,
            label=label,
            reason=flag_reason.get(
                f, "직접 판단 필요" if f == Flag.NEEDS_HUMAN_JUDGMENT else "직접 검토 필요"
            ),
        )
        for f in flags
    ]


def _recheck_items(r: ResultBase, target: str, label: str) -> list[ReviewItem]:
    if not r.needs_recheck:
        return []
    return [
        ReviewItem(kind="needs_recheck", target=target, label=label, reason=r.recheck_reason or "")
    ]


def _items_of_citation(c: Citation, target: str) -> list[ReviewItem]:
    label = _text(c.number)
    items = _field_item(c.number, f"{target}.number", label)
    items += _field_item(c.country, f"{target}.country", label)
    items += _field_item(c.cited_paragraphs, f"{target}.cited_paragraphs", label)
    if c.country.value is None:
        why = f"나라를 못 정함 ({c.country.raw_text or '원문 글자 없음'})"
    else:
        why = f"지원 안 하는 나라 {c.country.value}"
    return items + _flag_items(c.flags, target, label, {Flag.NEEDS_HUMAN_REVIEW: why})


def _items_of_rejection(rej: Rejection, target: str) -> list[ReviewItem]:
    label = _text(rej.article)
    items: list[ReviewItem] = []
    # 지원 안 하는 거절이유 안의 필드도 한 줄씩 낸다 (결과 status에서는 빠지지만 사람은 봐야 함)
    for name in ("article", "claims", "examiner_reasoning"):
        items += _field_item(getattr(rej, name), f"{target}.{name}", label)
    items += _recheck_items(rej, target, label)
    why = {Flag.NEEDS_HUMAN_REVIEW: f"지원 안 하는 거절이유 {label}"} if not rej.supported else {}
    items += _flag_items(rej.flags, target, label, why)
    for j, c in enumerate(rej.citations):
        items += _items_of_citation(c, f"{target}.citations[{j}]")
    return items


def _items_of_claim_row(row: ClaimRow, target: str) -> list[ReviewItem]:
    """청구항 줄 하나: 확인되지 않았으면 그 줄 경로에서 한 줄 (값은 이미 비어 있음)."""
    if row.claim is None or row.rejection is None:
        label = "청구항 줄"
    else:
        label = f"청구항 {row.claim}·거절이유 {row.rejection}"
    return _field_item(row, target, label)


def _items_of_oa_result(oa: OAResult, target: str) -> list[ReviewItem]:
    """OAResult 하나: 결과 단위 status 줄은 없이, 확인되지 않은 필드마다 한 줄."""
    items: list[ReviewItem] = []
    named = [
        "application_number",
        "dispatch_number",
        "notice_date",
        "response_due",
        "notice_kind",
        "examined_claims",
        "examined_claim_version",
    ]
    for name in named:
        v = getattr(oa, name)
        if v is not None:
            items += _field_item(v, f"{target}.{name}", oa.oa_id)
    for name in ("allowable_claims", "amendment_note"):
        items += _field_item(
            getattr(oa.examiner_hints, name), f"{target}.examiner_hints.{name}", oa.oa_id
        )
    items += _recheck_items(oa, target, oa.oa_id)
    items += _flag_items(oa.flags, target, oa.oa_id, {})
    for i, rej in enumerate(oa.rejections):
        items += _items_of_rejection(rej, f"{target}.rejections[{i}]")
    for i, row in enumerate(oa.claim_rows):
        items += _items_of_claim_row(row, f"{target}.claim_rows[{i}]")
    return items


def collect_review_items(results: list[ResultBase], materials: CaseMaterials) -> list[ReviewItem]:
    """결과들과 빠진 자료에서 검토할 사항을 모은다.

    OAResult는 필드까지 내려가 확인되지 않은 필드마다 한 줄.
    경로는 `oa_result[<oa_id>]...` (목록 위치가 아니라 OA 이름이라 순서가 바뀌어도 같은 값).
    필드를 모르는 일반 결과는 결과 status 한 줄. 조회 범위 내 없음은 정상 답이라 넣지 않는다.
    결과가 0개여도 빠진 자료 줄은 낸다 (경고는 남김).
    """
    if not results:
        logger.warning("collect_review_items: 결과가 0개")

    items: list[ReviewItem] = []
    for i, r in enumerate(results):
        if isinstance(r, OAResult):
            items += _items_of_oa_result(r, f"oa_result[{r.oa_id}]")
            continue
        target, label = f"results[{i}]", type(r).__name__
        if r.status.value == StatusValue.UNVERIFIED:
            reason = str(r.status.reason)
            items.append(ReviewItem(kind="unverified", target=target, label=label, reason=reason))
        elif r.status.value == StatusValue.CONFLICT:
            items.append(
                ReviewItem(kind="conflict", target=target, label=label, reason="값이 서로 충돌")
            )
        items += _recheck_items(r, target, label)
        items += _flag_items(r.flags, target, label, {})
    for i, m in enumerate(materials.missing):
        items.append(
            ReviewItem(
                kind="missing_material",
                target=f"materials.missing[{i}]",
                label=m.what,
                reason=str(m.lookup_result),
            )
        )
    return items


# ---------- F5 마무리 (docs/features/F5/design.md 2절) ----------

# 검토할 사항을 보여 주는 순서. 사람이 먼저 손대야 풀리는 것(자료 올리기)을 위에 둔다
_KIND_ORDER: list[ReviewKind] = [
    "missing_material",
    "conflict",
    "unverified",
    "needs_human_judgment",
    "needs_human_review",
    "needs_recheck",
]

_INPUT_UNVERIFIED = str(UnverifiedReason.INPUT_UNVERIFIED)


def sort_review_items(items: list[ReviewItem]) -> list[ReviewItem]:
    """종류 순서대로. 같은 종류 안에서는 들어온 순서 그대로 (sorted는 안정 정렬)."""
    return sorted(items, key=lambda i: _KIND_ORDER.index(i.kind))


def _document_item(doc: CaseDocument, index: int, kind: ReviewKind, reason: str) -> ReviewItem:
    return ReviewItem(
        kind=kind,
        target=f"materials.documents[{index}]",
        label=f"{doc.kind} {doc.document_id}",
        reason=reason,
    )


def document_review_items(doc: CaseDocument, index: int) -> list[ReviewItem]:
    """문서 하나의 원인 줄. 원인마다 한 줄: 묶기 상태 칸 하나, 글자 추출 상태 칸 하나.

    두 칸을 합치지 않는다 (합치면 같은 등급에서 앞 것이 이겨 body_missing이 지워진다).
    글자가 없어 생긴 묶기 not_extracted는 원인이 아니라 결과라 줄을 내지 않는다.
    """
    items: list[ReviewItem] = []
    text = doc.text_status
    no_text = (
        text is not None
        and text.value == StatusValue.UNVERIFIED
        and text.reason == UnverifiedReason.BODY_MISSING
    )
    for status, is_text in ((doc.status, False), (text, True)):
        if status is None:
            continue
        if status.value == StatusValue.CONFLICT:
            items.append(_document_item(doc, index, "conflict", "값이 서로 충돌"))
        elif status.value == StatusValue.UNVERIFIED:
            if not is_text and no_text and status.reason == UnverifiedReason.NOT_EXTRACTED:
                continue  # 글자가 없어서 번호를 못 읽은 것: body_missing 줄 하나로 충분
            items.append(_document_item(doc, index, "unverified", str(status.reason)))
    return items


def _is_grouped(it: ReviewItem) -> bool:
    """묶을 줄인지: 결과(oa_result[..]·results[..]) 안의 input_unverified 줄만.

    문서 줄(materials.documents[i])은 묶지 않는다
    (첫 `.` 앞으로 자르면 "materials"가 돼 갈 곳이 없다).
    """
    return it.reason == _INPUT_UNVERIFIED and it.target.startswith(("oa_result[", "results["))


def _group_input_unverified(items: list[ReviewItem]) -> list[ReviewItem]:
    """이유가 input_unverified인 줄(앞 입력 탓에 생긴 것)을 결과마다 한 줄로 묶는다.

    묶은 줄은 그 결과의 첫 줄 자리에 둔다. 원인 줄(다른 이유)은 그대로 둔다.
    """
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for it in items:
        if _is_grouped(it):
            result_target = it.target.split(".", 1)[0]  # 예: oa_result[oa_1]
            counts[result_target] = counts.get(result_target, 0) + 1
            m = re.fullmatch(r"oa_result\[(.*)\]", result_target)
            labels.setdefault(result_target, m.group(1) if m else it.label)

    out: list[ReviewItem] = []
    done: set[str] = set()
    for it in items:
        if not _is_grouped(it):
            out.append(it)
            continue
        result_target = it.target.split(".", 1)[0]
        if result_target in done:
            continue
        done.add(result_target)
        out.append(
            ReviewItem(
                kind="unverified",
                target=result_target,
                label=labels[result_target],
                reason=f"앞 입력이 확인되지 않음: 칸 {counts[result_target]}개",
            )
        )
    return out


def _dedupe(items: list[ReviewItem]) -> list[ReviewItem]:
    """같은 (target, kind, reason)은 하나만. 이유가 다르면 원인이 다르니 둘 다 둔다."""
    seen: set[tuple[str, str, str]] = set()
    out: list[ReviewItem] = []
    for it in items:
        key = (it.target, it.kind, it.reason)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def finalize_case_materials(results: list[ResultBase], materials: CaseMaterials) -> CaseMaterials:
    """⑥을 마무리한다: 모으기 + 문서 줄 + 묶기 + 순서 + 개수. 새 ⑥을 돌려준다 (입력은 안 바꿈).

    입력 ⑥에 이미 있던 review_items는 쓰지 않고 새로 모은다 (다시 불러도 줄이 불어나지 않게).
    모으다 예외가 나면 삼키지 않고 그대로 올린다 (빈 목록으로 저장되지 않게).
    """
    # 같은 종류 안에서는 문서 줄(원인)이 결과 줄(그 결과)보다 앞에 온다
    items: list[ReviewItem] = []
    for i, doc in enumerate(materials.documents):
        items += document_review_items(doc, i)
    items += collect_review_items(results, materials)
    items = sort_review_items(_dedupe(_group_input_unverified(items)))
    # 새로 만들어 개수 = 줄 수 검사를 거친다 (model_copy는 검사를 건너뜀)
    return CaseMaterials.model_validate(
        materials.model_dump() | {"review_items": items, "review_items_count": len(items)}
    )
