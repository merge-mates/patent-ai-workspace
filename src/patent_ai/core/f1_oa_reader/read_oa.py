"""read_oa: 통지서 쪽 글자 -> OAResult (design.md 2절 ③④⑤⑥, 7절).

규칙(코드)과 모델이 각각 뽑고, 원문 대조(merge)를 거친 값만 결과에 넣는다.
모델 호출 실패는 결과로 바꾸지 않고 예외를 그대로 던진다 (지휘가 실행 failed로 남김).
"""

import logging
import re
from collections.abc import Callable
from typing import Any

from patent_ai.core.f1_oa_reader.claim_rows import build_claim_rows
from patent_ai.core.f1_oa_reader.extraction import (
    CitationExtraction,
    Item,
    LooseOAExtraction,
    OAExtraction,
    RejectionExtraction,
)
from patent_ai.core.f1_oa_reader.model_input import MODES, ModelInput, model_input
from patent_ai.core.f1_oa_reader.rules import (
    expand_claims,
    extract_by_rules,
    loose_pattern,
    normalize_application_number,
    normalize_article,
    normalize_dispatch_number,
    notice_kind_of,
    parse_cited_locations,
)
from patent_ai.core.f1_oa_reader.support import citation_key, country_of, is_supported
from patent_ai.core.f1_oa_reader.tables import RejectionRow, rejection_rows
from patent_ai.core.f1_oa_reader.verify import Found, merge, unverified
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelConfigError, ModelOutputInvalid
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
def _settle(v: ExtractedValue, parse: Callable[[str], Any]) -> ExtractedValue:
    """글자만 대조한(compare_by="raw_text") 결과에 값을 붙인다.

    대조에 통과했는데 글자를 값 꼴로 못 읽으면 값 없이 확인되지 않음(애매). 글자·쪽은 남긴다.
    """
    if v.status.value != StatusValue.CONFIRMED:
        return v
    value = parse(v.raw_text or "")
    if value is None:
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS)
        return ExtractedValue(value=None, raw_text=v.raw_text, page=v.page, status=status)
    return v.model_copy(update={"value": value})


# 심사 대상 청구항을 가리키는 말 (공백 없앤 뒤 비교)
_ALL_CLAIMS = {"청구항전항", "전항", "전청구항", "모든청구항", "청구항전부"}


def _claims_parser(examined: ExtractedValue) -> Callable[[str], list[int] | None]:
    """대상 청구항 글자 -> 번호 목록. `청구항 전항`은 심사 대상 청구항으로 펼친다."""

    def parse(raw: str) -> list[int] | None:
        if "".join(raw.split()) in _ALL_CLAIMS:
            return list(examined.value) if examined.value else None  # 못 펼치면 None
        return expand_claims(raw)

    return parse


# ---- 글자 층 없음: 모델을 안 부르고 전부 input_unverified ----
def _result_without_text(document_id: str, oa_id: str) -> OAResult:
    def bad() -> ExtractedValue:
        return unverified(UnverifiedReason.INPUT_UNVERIFIED)

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
        examined_claims=bad(),
        examiner_hints=ExaminerHints(allowable_claims=bad(), amendment_note=bad()),
        rejections=[],
    )


# ---- 모델 호출 (검사 실패면 한 번 더) ----
_RETRY_NOTE = (
    "\n앞 답이 출력 형식 검사에 떨어졌습니다. 아래 오류를 고쳐 같은 형식으로 다시 답하세요.\n"
    "검사 오류:\n{error}\n"
)
_MAX_ERROR_CHARS = 2000  # 오류 문구가 길면 앞부분만 (프롬프트가 불어나지 않게)


def _input_mode() -> ModelInput:
    """config/f1.yaml read_oa.model_input. 없거나 모르는 값이면 멈춘다 (raw로 넘어가지 않음)."""
    mode = load_step_config(STEP).model_input
    if mode not in MODES:
        raise ModelConfigError(f"{STEP}의 model_input은 {MODES} 중 하나여야 함: {mode!r}")
    return mode  # type: ignore[return-value]


def _call(pages: PageText, ctx: RunContext) -> OAExtraction:
    # 모델에 넣는 글자만 바꾼다. 원문 대조는 아래에서 원본 pages로 한다
    text = model_input(pages, _input_mode())
    try:
        first = call_model(
            STEP, {"pages": text, "retry_note": ""}, OAExtraction, ctx=ctx, attempt=1
        )
        return first.parsed
    except ModelOutputInvalid as e:
        error = str(e)[:_MAX_ERROR_CHARS]
        logger.warning("read_oa: 모델 답이 검사에 떨어져 검사 오류를 붙여 한 번 더 부름")
    # 두 번째: 검사 오류 문구를 프롬프트에 넣는다. 목록 칸의 문자열만 받아 두는 판으로 검사하고
    # (그 줄은 claim_rows가 확인되지 않음으로 둔다) 그 밖의 검사 실패는 ModelOutputInvalid 그대로.
    variables = {"pages": text, "retry_note": _RETRY_NOTE.format(error=error)}
    second = call_model(STEP, variables, LooseOAExtraction, ctx=ctx, attempt=2)
    return second.parsed


# ---- 거절이유 하나 ----
def _label_of(number: ExtractedValue, labels: dict[str, str]) -> str:
    """인용문헌 라벨: OA에 나온 순서로 D1, D2… 같은 문헌(키나 원문 표기가 같음)은 같은 라벨."""
    identity = number.value or "".join((number.raw_text or "").split())
    if not identity:  # 번호를 못 읽은 것은 문헌을 알 수 없으니 새 라벨
        return f"D{len(labels) + 1}"
    return labels.setdefault(identity, f"D{len(labels) + 1}")


def _citation(c: CitationExtraction, pages: PageText, labels: dict[str, str]) -> Citation:
    raw_number = merge(
        None, _found(c.number), pages, compare_by="raw_text", field="citation.number"
    )
    # 나라는 대조를 통과한 번호 글자에서 정규식으로 정한다
    country = country_of(raw_number.raw_text or "", raw_number.page)

    def key_of(raw: str) -> str | None:
        key = citation_key(raw)
        # 키의 나라와 판정한 나라가 어긋나면 꼴을 못 정한 것으로 본다
        return key if key is not None and key[:2] == country.value else None

    number = _settle(raw_number, key_of)  # 논문·꼴 불명은 값 null + 애매
    supported = country.value in SUPPORTED_COUNTRIES
    paragraphs = _settle(
        merge(
            None, _found(c.cited_paragraphs), pages, compare_by="raw_text", field="cited_paragraphs"
        ),
        parse_cited_locations,
    )
    return Citation(
        label=_label_of(number, labels),
        number=number,
        country=country,
        country_supported=supported,
        cited_paragraphs=paragraphs,
        flags=[] if supported else [Flag.NEEDS_HUMAN_REVIEW],
    )


def _rejection(
    no: int,
    r: RejectionExtraction,
    pages: PageText,
    examined: ExtractedValue,
    labels: dict[str, str],
    row: RejectionRow | None = None,
) -> dict:
    # 거절이유 표 줄(row)이 있으면 조문·대상 청구항의 규칙 쪽 값으로 쓴다 (모델 값과 대조).
    # 다음 쪽으로 잘렸을 수 있는 줄(조각을 못 찾음)은 쓰지 않는다:
    # 잘린 앞부분만으로 확인됨이 되지 않게
    use = row is not None and not row.may_be_cut
    rule_article = Found(None, row.article, row.page) if use else None
    rule_claims = Found(None, row.part, row.page) if use else None
    article = merge(
        rule_article, _found(r.article), pages, derive=normalize_article, field="article"
    )
    claims = merge(
        rule_claims, _found(r.claims), pages, derive=_claims_parser(examined), field="claims"
    )
    # 요지: 원문 글자만 대조하고, 요지 글(value)은 대조 통과 때만 붙인다
    reasoning = merge(
        None, _found(r.examiner_reasoning), pages, compare_by="raw_text", field="reasoning"
    )
    if reasoning.status.value == StatusValue.CONFIRMED and r.examiner_reasoning is not None:
        reasoning = reasoning.model_copy(update={"value": r.examiner_reasoning.value})
    supported = article.value is not None and is_supported(article.value)
    return {
        "no": no,
        "article": article,
        "supported": supported,
        "claims": claims,
        "citations": [_citation(c, pages, labels) for c in r.citations],
        "examiner_reasoning": reasoning,
        "flags": [] if supported else [Flag.NEEDS_HUMAN_REVIEW],
    }


# 힌트 칸 제목 (표기가 둘 이상일 수 있음). [가정] 표본 OA로 확인 (#22)
_CLAIMS_TITLES = [loose_pattern("특허 가능한 청구항")]
_NOTE_TITLES = [loose_pattern("보정에 관한 참고사항"), loose_pattern("보정서 제출시 참고사항")]


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
    # 값 = 원문 대조를 통과한 글자 그대로 (모델이 준 value는 쓰지 않는다, 이슈 #154).
    # 정답 형식(f1-oa-gold.md)도 원문 문장 그대로라 화면·채점이 value를 바로 쓴다.
    return merge(None, _found(item), pages, derive=_original_sentence, field="amendment_note")


def _original_sentence(raw_text: str) -> str | None:
    """보정 참고사항 값: 원문 글자의 앞뒤 공백만 뺀다. 비면 None(못 씀)."""
    return raw_text.strip() or None


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
    # 심사 대상 청구항을 먼저: `청구항 전항`을 펼칠 때 쓴다
    examined = merge(
        None, _found(model.examined_claims), pages, derive=expand_claims, field="examined_claims"
    )
    labels: dict[str, str] = {}  # 인용문헌 라벨 (거절이유를 건너 같은 문헌은 같은 라벨)
    # 거절이유 표 줄 (쪽을 넘어간 칸은 이어 붙임, task-8). 순번으로 모델 거절이유와 짝짓는다
    table = {row.no: row for row in rejection_rows(pages)}
    if not table and any(p.tables for p in pages.pages):
        logger.warning(
            "read_oa %s: 표는 있는데 거절이유 표 머리 줄을 못 찾음 (모델 값만 씀)", oa_id
        )
    if table and len(table) != len(model.rejections):
        logger.warning(
            "read_oa %s: 거절이유 표 줄 %d개와 모델 거절이유 %d개가 다름",
            oa_id,
            len(table),
            len(model.rejections),
        )
    rejections = [
        _rejection(i, r, pages, examined, labels, table.get(i))
        for i, r in enumerate(model.rejections, start=1)
    ]
    claim_rows = build_claim_rows(model.claim_rows, rejections, pages, _claims_parser(examined))
    if not claim_rows and any(r["supported"] for r in rejections):
        logger.warning("read_oa %s: 모델이 청구항 줄(claim_rows)을 하나도 주지 않음", oa_id)
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
        examined_claims=examined,
        examiner_hints=ExaminerHints(
            allowable_claims=_hint_claims(model.allowable_claims, pages),
            amendment_note=_hint_note(model.amendment_note, pages),
        ),
        rejections=rejections,
        claim_rows=claim_rows,
    )
