"""read_oa: 통지서 쪽 글자 -> OAResult (design.md 2절 ③④⑤⑥, 7절).

규칙(코드)과 모델이 각각 뽑고, 원문 대조(merge)를 거친 값만 결과에 넣는다.
모델 호출 실패는 결과로 바꾸지 않고 예외를 그대로 던진다 (지휘가 실행 failed로 남김).
"""

import logging
import re

from patent_ai.core.f1_oa_reader.extraction import (
    CitationExtraction,
    Item,
    OAExtraction,
    RejectionExtraction,
)
from patent_ai.core.f1_oa_reader.rules import (
    expand_claims,
    extract_by_rules,
    normalize_application_number,
    normalize_article,
    normalize_dispatch_number,
    notice_kind_of,
)
from patent_ai.core.f1_oa_reader.support import country_of, is_supported
from patent_ai.core.f1_oa_reader.verify import Found, merge
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import (
    ExtractedValue,
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import (
    SUPPORTED_COUNTRIES,
    Citation,
    ExaminerHints,
    NoticeKind,
    OAResult,
    build_oa_result,
)

logger = logging.getLogger(__name__)

STEP = "f1.read_oa"


# ---- 모델이 준 값 -> 합치기용 Found ----
def _found(item: Item | None) -> Found | None:
    """모델 값 하나를 Found로. 칸이 null이면 None(못 뽑음)."""
    if item is None:
        return None
    return Found(value=item.value, raw_text=item.raw_text, page=item.page, ambiguous=item.ambiguous)


# ---- 원문 글자에서 값을 다시 뽑는 함수들 (모델이 준 value는 믿지 않는다) ----
def _paragraphs_of(raw: str) -> list[str] | None:
    """`식별번호 [0023], [0031]` -> ["0023", "0031"]. 하나도 없으면 None."""
    found = re.findall(r"\[(\d+)\]", raw)
    return found or None


def _number_of(raw: str) -> str | None:
    """인용문헌 번호는 원문 표기를 (공백만 정리해) 그대로 쓴다."""
    text = " ".join(raw.split())
    return text or None


def _unverified(reason: UnverifiedReason) -> ExtractedValue:
    return ExtractedValue(status=Status(value=StatusValue.UNVERIFIED, reason=reason))


# ---- 글자 층 없음: 모델을 안 부르고 전부 input_unverified ----
def _result_without_text(document_id: str, oa_id: str) -> OAResult:
    def bad() -> ExtractedValue:
        return _unverified(UnverifiedReason.INPUT_UNVERIFIED)

    kind = ExtractedValue[NoticeKind](
        value=NoticeKind.UNKNOWN,
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED),
    )
    logger.warning("read_oa %s: 글자 층이 없어 모델을 부르지 않음 (input_unverified)", oa_id)
    return build_oa_result(
        document_id=document_id,
        oa_id=oa_id,
        application_number=bad(),
        dispatch_number=bad(),
        notice_date=bad(),
        response_due=bad(),
        notice_kind=kind,
        examiner_hints=ExaminerHints(allowable_claims=bad(), amendment_note=bad()),
        rejections=[],
    )


# ---- 모델 호출 (검사 실패면 한 번 더) ----
def _call(pages: PageText, ctx: RunContext) -> OAExtraction:
    text = "\n\n".join(f"[쪽 {p.page}]\n{p.text}" for p in pages.pages)
    try:
        first = call_model(STEP, {"pages": text}, OAExtraction, ctx=ctx, attempt=1)
        return first.parsed
    except ModelOutputInvalid:
        logger.warning("read_oa: 모델 답이 검사에 떨어져 한 번 더 부름")
    # 두 번째도 떨어지면 ModelOutputInvalid를 그대로 던진다. 전송 실패·상한도 그대로
    second = call_model(STEP, {"pages": text}, OAExtraction, ctx=ctx, attempt=2)
    return second.parsed


# ---- 거절이유 하나 ----
def _citation(c: CitationExtraction, pages: PageText) -> Citation:
    number = merge(None, _found(c.number), pages, derive=_number_of, field="citation.number")
    # 나라는 대조를 통과한 번호 글자에서 정규식으로 정한다
    country = country_of(number.raw_text or "", number.page)
    supported = country.value in SUPPORTED_COUNTRIES
    paragraphs = merge(
        None, _found(c.cited_paragraphs), pages, derive=_paragraphs_of, field="cited_paragraphs"
    )
    return Citation(
        number=number,
        country=country,
        country_supported=supported,
        cited_paragraphs=paragraphs,
        flags=[] if supported else [Flag.NEEDS_HUMAN_REVIEW],
    )


def _rejection(r: RejectionExtraction, pages: PageText) -> dict:
    article = merge(None, _found(r.article), pages, derive=normalize_article, field="article")
    claims = merge(None, _found(r.claims), pages, derive=expand_claims, field="claims")
    # 요지: 원문 글자만 대조하고, 요지 글(value)은 대조 통과 때만 붙인다
    reasoning = merge(
        None, _found(r.examiner_reasoning), pages, compare_by="raw_text", field="reasoning"
    )
    if reasoning.status.value == StatusValue.CONFIRMED and r.examiner_reasoning is not None:
        reasoning = reasoning.model_copy(update={"value": r.examiner_reasoning.value})
    supported = article.value is not None and is_supported(article.value)
    return {
        "article": article,
        "supported": supported,
        "claims": claims,
        "citations": [_citation(c, pages) for c in r.citations],
        "examiner_reasoning": reasoning,
        "flags": [] if supported else [Flag.NEEDS_HUMAN_REVIEW],
    }


def _loose(title: str) -> re.Pattern[str]:
    """제목 글자 사이에 공백·줄바꿈이 끼어도 찾는 정규식."""
    return re.compile(r"\s*".join(re.escape(ch) for ch in title if not ch.isspace()))


# 힌트 칸 제목 (표기가 둘 이상일 수 있음). [가정] 표본 OA로 확인 (#22)
_CLAIMS_TITLES = [_loose("특허 가능한 청구항")]
_NOTE_TITLES = [_loose("보정에 관한 참고사항"), _loose("보정서 제출시 참고사항")]


def _has_title(pages: PageText, titles: list[re.Pattern[str]]) -> bool:
    return any(t.search(p.text) for p in pages.pages for t in titles)


def _hint_missing(pages: PageText, titles: list[re.Pattern[str]]) -> Status:
    """모델이 null을 준 힌트. 쪽 글자에 칸 제목이 있으면 못 뽑은 것, 없을 때만 "칸 없음"."""
    if _has_title(pages, titles):
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    return Status(value=StatusValue.CONFIRMED, checked="원문에 칸 없음, 모든 쪽 글자를 봄")


def _hint_claims(item: Item | None, pages: PageText) -> ExtractedValue:
    if item is None:
        status = _hint_missing(pages, _CLAIMS_TITLES)
        return ExtractedValue(
            value=[] if status.value == StatusValue.CONFIRMED else None, status=status
        )
    return merge(None, _found(item), pages, derive=expand_claims, field="allowable_claims")


def _hint_note(item: Item | None, pages: PageText) -> ExtractedValue:
    if item is None:
        return ExtractedValue(status=_hint_missing(pages, _NOTE_TITLES))
    return merge(None, _found(item), pages, compare_by="raw_text", field="amendment_note")


def read_oa(
    pages: PageText, document_id: str, oa_id: str, run_id: str, *, ctx: RunContext
) -> OAResult:
    """통지서 쪽 글자에서 OA 필드와 거절이유를 뽑아 OAResult로 돌려준다.

    run_id는 ctx.run_id와 같아야 한다 (호출 기록·상한이 같은 실행에 쌓임).
    """
    if run_id != ctx.run_id:
        raise ValueError(f"run_id {run_id!r}가 ctx.run_id {ctx.run_id!r}와 다름")
    # 1) 글자 층이 없으면 모델을 부르지 않는다
    if pages.status.value == StatusValue.UNVERIFIED:
        return _result_without_text(document_id, oa_id)

    # 2) 규칙 추출 + 모델 추출 (모델은 한 번, 검사 실패 때 한 번 더)
    rules = extract_by_rules(pages)
    model = _call(pages, ctx)

    # 3) 필드마다 원문 대조·합치기 (필드 출처 표)
    rejections = [_rejection(r, pages) for r in model.rejections]
    return build_oa_result(
        document_id=document_id,
        oa_id=oa_id,
        application_number=merge(
            rules.application_number,
            _found(model.application_number),
            pages,
            derive=normalize_application_number,
            field="application_number",
        ),
        dispatch_number=merge(
            rules.dispatch_number,
            _found(model.dispatch_number),
            pages,
            derive=normalize_dispatch_number,
            field="dispatch_number",
        ),
        # 날짜는 규칙만, value 없이 글자만 비교
        notice_date=merge(
            rules.notice_date, None, pages, compare_by="raw_text", field="notice_date"
        ),
        response_due=merge(
            rules.response_due, None, pages, compare_by="raw_text", field="response_due"
        ),
        notice_kind=notice_kind_of(pages),  # 규칙만
        examiner_hints=ExaminerHints(
            allowable_claims=_hint_claims(model.allowable_claims, pages),
            amendment_note=_hint_note(model.amendment_note, pages),
        ),
        rejections=rejections,
    )
