"""명확성 단계 (F3 ③): 명확성 판단 단위(청구항 하나) -> 짚은 문구마다 ClarityReview.

- OA가 짚은 문구(F1 청구항 줄의 clarity_terms)가 청구항 원문 어디에 있는지는 코드가 찾는다.
- 용어 정의는 그 사건 출원서(F3Inputs.spec)만, 메모리 BM25로 상위 k 조각을 뽑아 모델에 준다
  (DB·임베딩 없음). 문제 유형과 근거는 모델이 본다.
- 모델이 고른 정의 근거는 코드가 그 명세서 조각 글자와 대조한다. 떨어지면 버린다.
- 못 찾으면 "조회 범위 내 없음" + 찾아본 범위. "정의가 없다"고 단정하는 글을 만들지 않는다.
"""

import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.f3_claim_compare.examiner import find_claim_row
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Settings
from patent_ai.core.f3_claim_compare.textmatch import find_span
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import Evidence, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import ClarityReview
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult, RejectionKind
from patent_ai.retrieval.contract import Searcher, get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

logger = logging.getLogger(__name__)

STEP = "f3.clarity"
# 메모리에만 있는 색인 이름 (DB 색인 판이 아니다. 근거에는 chunk_id·색인 판을 싣지 않는다)
_SPEC_INDEX = "cite-spec-memory"
# 줄 맨 앞의 식별번호 `【0016】`·`[0016]` (인용문헌 색인이 문단을 나누는 꼴과 같다)
_PARAGRAPH_HEAD = re.compile(r"^\s*[【\[](\d{4})[】\]]")
CLARITY = RejectionKind.CLARITY


# ---- 모델이 돌려주는 출력 스키마 ----
class IssueType(StrEnum):
    NO_ANTECEDENT = "no_antecedent"  # 앞에 없던 '상기 ○○'
    OPTIONAL_EXPRESSION = "optional_expression"  # 선택적·정도 표현
    TERM_DIFFERS_FROM_SPEC = "term_differs_from_spec"  # 명세서와 다른 용어
    OTHER = "other"


_ISSUE_NAMES = {
    IssueType.NO_ANTECEDENT: "앞에 없던 지시 표현",
    IssueType.OPTIONAL_EXPRESSION: "선택적·정도 표현",
    IssueType.TERM_DIFFERS_FROM_SPEC: "명세서와 다른 용어",
    IssueType.OTHER: "그 밖",
}


class DefinitionPick(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    quote: str  # 그 조각 글에서 그대로 옮긴 부분


class TermAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str
    issue_type: IssueType
    note: str
    definition: DefinitionPick | None = None


class ClarityAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    terms: list[TermAnswer] = []


class ClarityOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reviews: list[ClarityReview] = Field(default_factory=list)
    held_tasks: list[HeldTask] = Field(default_factory=list)


# ---- 명세서 쪼개기: 쪽 안에서 식별번호마다 ----
@dataclass(frozen=True)
class SpecChunk:
    """명세서 조각 하나와 그 조각이 있는 쪽."""

    chunk: Chunk
    page: int


def split_spec(spec: PageText) -> list[SpecChunk]:
    """명세서 쪽 글자를 조각으로 쪼갠다 (답이 정해진 코드 도구).

    쪽 안에서 줄 맨 앞 식별번호(`【0016】`)마다 자른다. 조각은 쪽을 넘지 않는다:
    다음 쪽으로 넘어간 문단의 뒷부분은 같은 식별번호의 새 조각(그 쪽)으로 둔다.
    식별번호가 아직 안 나온 글(첫 쪽 머리, 식별번호 없는 명세서)은 쪽 하나가 조각이다.
    """
    out: list[SpecChunk] = []
    current: int | None = None  # 지금 이어지는 식별번호

    def add(page: int, number: int | None, lines: list[str]) -> None:
        text = "\n".join(lines).strip()
        if not text:
            return
        if number is None:
            location = Location(kind="page", start=page, end=page, label=f"{page}쪽")
            key = f"pg{page}"
        else:
            label = f"[{number:04d}]"
            location = Location(kind="paragraph", start=number, end=number, label=label)
            key = f"pg{page}:p{number:04d}"
        chunk = Chunk(
            chunk_id=f"{_SPEC_INDEX}:{spec.document_id}:{key}",
            index_version=_SPEC_INDEX,
            doc_id=spec.document_id,
            chunk_kind="body",
            location=location,
            edition=Edition(status="not_applicable"),
            text=text,
        )
        out.append(SpecChunk(chunk, page))

    for page in sorted(spec.pages, key=lambda p: p.page):
        lines: list[str] = []
        for line in page.text.splitlines():
            m = _PARAGRAPH_HEAD.match(line)
            if m:
                add(page.page, current, lines)
                current, lines = int(m.group(1)), []
            lines.append(line)
        add(page.page, current, lines)
    return out


# ---- 작은 도우미 ----
def _confirmed(checked: str) -> Status:
    return Status(value=StatusValue.CONFIRMED, checked=checked)


def _unverified(reason: UnverifiedReason) -> Status:
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


@dataclass(frozen=True)
class SpecIndex:
    """그 사건 출원서의 조각과, 그 조각만 담은 메모리 BM25 검색기."""

    chunks: list[SpecChunk]
    searcher: Searcher | None  # 조각이 0개면 None


def build_spec_index(spec: PageText | None, settings: F3Settings) -> SpecIndex:
    """출원서를 쪼개 메모리 검색기를 만든다. 사건마다 한 번만 만들어 단위들이 같이 쓴다."""
    chunks = split_spec(spec) if spec is not None else []
    if spec is not None and not chunks:
        logger.warning("clarity: 명세서 %s의 조각이 0개 (글자가 없음)", spec.document_id)
    return SpecIndex(chunks, _spec_searcher(chunks, settings) if chunks else None)


def _spec_searcher(chunks: list[SpecChunk], settings: F3Settings) -> Searcher:
    repo = InMemoryChunkRepository({"cite": [c.chunk for c in chunks]})
    search = settings.search
    bm25_settings = {
        "index_version": _SPEC_INDEX,
        "tokenizer": search.tokenizer,
        "pos_tags": search.pos_tags,
        "bm25": search.bm25,
    }
    return get_searcher("bm25", repo, bm25_settings)


@dataclass
class _Term:
    """청구항 원문에서 위치를 찾은 문구 하나."""

    term: str
    location: str  # 사람이 읽는 위치
    candidates: dict[str, SpecChunk]  # 모델에 보여 줄 명세서 조각 (chunk_id -> 조각)


@dataclass
class _Judged:
    answer: TermAnswer
    definition: Evidence | None = None
    dropped: bool = False  # 모델이 준 정의 근거가 대조에 떨어져 버렸나


def _locate(term: str, claim: int, claim_text: str) -> str | None:
    """문구가 청구항 원문에 그대로 있으면 위치 글, 없으면 None (공백 줄이기만 허용)."""
    span = find_span(term, claim_text)
    if span is None:
        return None
    return f"청구항 {claim} [글자 {span[0]}-{span[1]}]"


# ---- 모델 답 대조 ----
def _check(
    answer: ClarityAnswer, claim: int, terms: list[_Term], spec: PageText | None, min_chars: int
) -> tuple[dict[str, _Judged], list[str]]:
    errors: list[str] = []
    if answer.claim != claim:
        errors.append(f"claim은 {claim}이어야 함 (받은 값 {answer.claim})")
    judged: dict[str, _Judged] = {}
    for i, item in enumerate(answer.terms):
        mine = next((t for t in terms if _same(t.term, item.term)), None)
        if mine is None or mine.term in judged:
            errors.append(f"terms[{i}]: 받은 문구가 아니거나 두 번 나옴: {item.term!r}")
            continue
        one = _Judged(item)
        if not item.note.strip():
            errors.append(f"terms[{i}]: note가 비어 있음")
        pick = item.definition
        if pick is not None:
            found = mine.candidates.get(pick.chunk_id)
            span = find_span(pick.quote, found.chunk.text) if found else None
            # 아주 짧은 글자는 아무 조각에나 맞으므로 근거로 받지 않는다
            too_short = len("".join(pick.quote.split())) < min_chars
            if found is None:
                errors.append(f"terms[{i}]: 후보에 없는 chunk_id {pick.chunk_id!r}")
            elif span is None:
                errors.append(f"terms[{i}]: quote가 그 조각 글에 그대로 없음: {pick.quote!r}")
            elif too_short:
                errors.append(f"terms[{i}]: quote가 너무 짧음 ({min_chars}자 이상): {pick.quote!r}")
            if found is None or span is None or too_short:
                one.dropped = True
            else:
                one.definition = Evidence(
                    document_id=spec.document_id if spec else found.chunk.doc_id,
                    page=found.page,
                    location=found.chunk.location.label,
                    raw_text=found.chunk.text[span[0] : span[1]],
                )
        judged[mine.term] = one
    missing = [t.term for t in terms if t.term not in judged]
    if missing:
        errors.append(f"terms에 빠진 문구: {missing}")
    return judged, errors


_RETRY_NOTE = (
    "\n앞 답이 검사에 떨어졌습니다. 아래 오류를 고쳐 같은 형식으로 다시 답하세요.\n"
    "검사 오류:\n{error}\n"
)
_MAX_ERROR_CHARS = 2000


def _ask(
    unit: JudgmentUnit, terms: list[_Term], config: F3Config, ctx: RunContext
) -> dict[str, _Judged]:
    """모델 1회. 형식이나 대조 검사에 떨어지면 검사 오류를 붙여 한 번만 더 부른다."""
    claim = unit.representative_claim
    claims = config.inputs.claims_at_oa
    read_with = [f"청구항 {n}: {claims[n]}" for n in unit.read_with if n in claims]
    shown = [
        {
            "term": t.term,
            "candidates": [
                {"chunk_id": cid, "text": c.chunk.text} for cid, c in sorted(t.candidates.items())
            ],
        }
        for t in terms
    ]
    variables = {
        "claim": str(claim),
        "claim_text": claims.get(claim, ""),
        "read_with": "\n".join(read_with) or "(없음)",
        "terms": json.dumps(shown, ensure_ascii=False, indent=1),
        "retry_note": "",
    }
    spec = config.inputs.spec
    min_chars = config.settings.clarity_search.min_quote_chars
    try:
        first = call_model(STEP, variables, ClarityAnswer, ctx=ctx, attempt=1)
        judged, errors = _check(first.parsed, claim, terms, spec, min_chars)
        if not errors:
            return judged
        error = "\n".join(errors)
    except ModelOutputInvalid as e:
        error = str(e)
    logger.warning("clarity 청구항 %d: 답이 검사에 떨어져 검사 오류를 붙여 한 번 더 부름", claim)
    variables["retry_note"] = _RETRY_NOTE.format(error=error[:_MAX_ERROR_CHARS])
    second = call_model(STEP, variables, ClarityAnswer, ctx=ctx, attempt=2)
    judged, errors = _check(second.parsed, claim, terms, spec, min_chars)
    if errors:
        logger.warning("clarity 청구항 %d: 다시 불러도 검사 오류 %d건", claim, len(errors))
    return judged


# ---- 단위 하나 ----
def review_clarity_unit(
    unit: JudgmentUnit,
    oa: OAResult,
    config: F3Config,
    *,
    ctx: RunContext,
    spec_index: SpecIndex | None = None,
) -> ClarityOutput:
    """명확성 판단 단위(청구항 하나)의 짚은 문구마다 ClarityReview를 만든다.

    spec_index: build_spec_index로 미리 만든 출원서 색인 (안 주면 여기서 만든다).
    """
    if unit.rejection_kind != CLARITY:
        raise ValueError(f"명확성 단계는 명확성 단위만 받는다: {unit.unit_id}")
    claim = unit.representative_claim
    inputs, settings = config.inputs, config.settings
    row = find_claim_row(oa, unit.rejection, claim)
    wanted = list(dict.fromkeys(row.clarity_terms)) if row is not None else []
    if not wanted:
        # 따옴표로 짚은 문구가 없으면 검토(term 필수)를 만들 수 없다. 버리지 않고 보류로 남긴다
        logger.warning("clarity %s: OA가 짚은 문구가 없어 검토를 못 만듦 (보류)", unit.unit_id)
        held = HeldTask(
            task=f"f3_clarity:{unit.unit_id}", waiting_for="OA가 짚은 문구 확인 (직접 확인)"
        )
        return ClarityOutput(held_tasks=[held])

    def review(term: str, location: str, status: Status, note: str, definition=None):
        return ClarityReview(
            unit_id=unit.unit_id,
            claim=claim,
            term=term,
            claim_location=location,
            spec_definition=definition,
            note=note,
            status=status,
        )

    # 1) 짚은 문구가 청구항 원문에 있는지 코드로 확인
    claim_text = inputs.claims_at_oa.get(claim, "")
    index = spec_index or build_spec_index(inputs.spec, settings)
    chunks, searcher = index.chunks, index.searcher
    k = settings.clarity_search.k
    located: list[_Term] = []
    lost: list[str] = []
    for term in wanted:
        location = _locate(term, claim, claim_text)
        if location is None:
            lost.append(term)
            continue
        candidates: dict[str, SpecChunk] = {}
        if searcher is not None:
            # 2) 그 사건 출원서 안에서만 문구로 찾는다
            by_id = {c.chunk.chunk_id: c for c in chunks}
            for hit in searcher.search(term, "cite", "bm25", k).hits:
                candidates[hit.chunk_id] = by_id[hit.chunk_id]
        located.append(_Term(term, location, candidates))
    if lost:
        logger.warning(
            "clarity %s: 짚은 문구 %d개를 청구항 원문에서 못 찾음", unit.unit_id, len(lost)
        )

    # 3) 모델: 문제 유형과 정의 근거
    judged = _ask(unit, located, config, ctx) if located else {}

    # 4) 문구마다 결과 (OA가 짚은 순서 그대로)
    input_ok = inputs.claims_status.value == StatusValue.CONFIRMED
    scope = f"출원서 조각 {len(chunks)}개 중 bm25 상위 {k}"
    by_term = {t.term: t for t in located}
    reviews: list[ClarityReview] = []
    for term in wanted:
        if term in lost:
            status = _unverified(UnverifiedReason.NOT_EXTRACTED)
            note = "OA가 짚은 문구를 청구항 원문에서 찾지 못함 (직접 확인)"
            reviews.append(review(term, f"청구항 {claim} (위치 확인되지 않음)", status, note))
            continue
        one = judged.get(term)
        location = by_term[term].location
        if one is None:
            status = _unverified(UnverifiedReason.NOT_EXTRACTED)
            reviews.append(review(term, location, status, "모델이 이 문구 검토를 주지 않음"))
            continue
        note = f"[문제 유형 후보: {_ISSUE_NAMES[one.answer.issue_type]}] {one.answer.note.strip()}"
        if not input_ok:
            status = _unverified(UnverifiedReason.INPUT_UNVERIFIED)
        elif one.dropped:
            status = _unverified(UnverifiedReason.EVIDENCE_REJECTED)
        elif one.definition is not None:
            status = _confirmed(
                "짚은 문구가 청구항 원문에 있고 정의 근거 글자가 명세서 그 쪽에 있음"
            )
        elif not chunks:
            status = _unverified(UnverifiedReason.BODY_MISSING)  # 명세서가 없거나 글자가 없음
        else:
            # 못 찾음: 없다고 단정하지 않고 찾아본 범위를 남긴다
            status = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
        reviews.append(review(term, location, status, note, one.definition))
    return ClarityOutput(reviews=reviews)


def review_clarity_units(
    units: list[JudgmentUnit], oa: OAResult, config: F3Config, *, ctx: RunContext
) -> ClarityOutput:
    """명확성 단위만 골라 순서대로 검토해 한데 모은다."""
    reviews: list[ClarityReview] = []
    held: list[HeldTask] = []
    mine = [u for u in sorted(units, key=lambda u: u.order) if u.rejection_kind == CLARITY]
    if not mine:
        return ClarityOutput()
    index = build_spec_index(config.inputs.spec, config.settings)  # 사건마다 한 번
    for unit in mine:
        out = review_clarity_unit(unit, oa, config, ctx=ctx, spec_index=index)
        reviews += out.reviews
        held += out.held_tasks
    return ClarityOutput(reviews=reviews, held_tasks=held)
