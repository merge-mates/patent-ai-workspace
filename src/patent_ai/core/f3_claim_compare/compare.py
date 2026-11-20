"""진보성·신규성 대비 단계 (F3 ②③): 판단 단위 하나 -> ComparisonTable.

청구항마다: 구성요소 글자를 질의로 인용문헌 안에서 검색(상위 k) -> 모델 1회가 구성요소 × 후보 문단을
판정 -> 코드가 근거를 후보 조각과 대조 -> 줄(ComparisonRow)을 만든다.
- 검색 질의는 구성요소 원문뿐이다. 심사관이 짚은 위치는 질의에 절대 넣지 않는다.
- 심사관 지정 조각은 (설정이 켜져 있을 때만) 표시 없이 후보에 더하고, 줄의 출처는 코드가 붙인다.
- 근거를 못 고르면 "조회 범위 내 없음" + 찾아본 범위. "없다"고 단정하는 글을 만들지 않는다.
- 신규성은 인용문헌 하나와만: 인용문헌마다 모델을 따로 부르고 표도 따로 만든다.
"""

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.f3_claim_compare.citations import ResolvedCitation, resolve_citations
from patent_ai.core.f3_claim_compare.elements import ClaimElement, SplitClaim
from patent_ai.core.f3_claim_compare.examiner import (
    examiner_locations,
    find_claim_row,
    match_location,
)
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Settings
from patent_ai.core.f3_claim_compare.result import ExaminerLocationRow, SearchLogRow
from patent_ai.core.f3_claim_compare.textmatch import find_span
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.embed import query_embedder
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import Evidence, Flag, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import (
    ComparisonRow,
    ComparisonTable,
    InventiveSummary,
    Judgment,
    NoveltySummary,
    NoveltyVerdict,
    ParagraphSource,
    summarize_table_status,
)
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult, Rejection, RejectionKind
from patent_ai.retrieval.contract import Embed, Searcher, get_searcher
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Chunk, SearchResult

logger = logging.getLogger(__name__)

STEP = "f3.compare"
EMBED_STEP = "f3.embed"
_MODES = ("bm25", "vector", "hybrid")


# ---- 모델이 돌려주는 출력 스키마 ----
class EvidencePick(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str  # 후보 조각 ID
    quote: str  # 그 조각 글에서 그대로 옮긴 부분


class RowAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    element_no: int
    citation: str  # 라벨 D1…
    judgment: Judgment
    evidence: list[EvidencePick] = []


class CompareAnswer(BaseModel):
    """모델 답. 상태·출처(심사관 지정/AI 찾음)는 없다: 코드가 정한다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    rows: list[RowAnswer] = []


# ---- 이 단계가 돌려주는 것 ----
class CompareOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tables: list[ComparisonTable] = Field(default_factory=list)
    held_tasks: list[HeldTask] = Field(default_factory=list)
    search_log: list[SearchLogRow] = Field(default_factory=list)
    examiner_locations: list[ExaminerLocationRow] = Field(default_factory=list)


# ---- 검색기 만들기 (진짜 DB 저장소·진짜 임베딩은 부르는 쪽이 넘긴다) ----
def memo_embed(embed: Embed) -> Embed:
    """같은 글은 한 번만 임베딩한다 (구성요소 하나를 인용문헌마다 찾아도 호출은 1번)."""
    seen: dict[str, list[float]] = {}

    def one(text: str) -> list[float]:
        if text not in seen:
            seen[text] = embed(text)
        return seen[text]

    return one


def f3_query_embedder(ctx: RunContext) -> Embed:
    """질의 임베딩 함수 (config/f3.yaml embed 단계, 캐시·호출 상한·기록은 core/llm이 한다)."""
    return memo_embed(query_embedder(EMBED_STEP, ctx))


def make_searcher(settings: F3Settings, repo: ChunkRepository, embed: Embed | None) -> Searcher:
    """설정의 검색 구현으로 검색기를 만든다 (계약 검사 래퍼 포함)."""
    search = settings.search
    return get_searcher(search.impl, repo, search.searcher_settings(), embed)


# ---- 작은 도우미 ----
def _confirmed(checked: str) -> Status:
    return Status(value=StatusValue.CONFIRMED, checked=checked)


def _unverified(reason: UnverifiedReason) -> Status:
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def _scope_text(cite: ResolvedCitation, settings: F3Settings) -> str:
    """찾아본 범위를 사람이 읽는 글로."""
    s = settings.search
    return f"{cite.label} 조각 {cite.chunk_count}개 중 {s.impl} 상위 {s.k} ({s.index_version})"


@dataclass
class _Candidate:
    """모델에 보여 줄 후보 조각 하나."""

    chunk: Chunk
    label: str  # 어느 인용문헌의 조각인가
    ranks: dict[int, int] = field(default_factory=dict)  # 구성요소 번호 -> 검색 순위
    examiner: bool = False  # 심사관이 짚은 위치의 조각인가 (모델에는 보여 주지 않는다)


@dataclass
class _Judged:
    """구성요소 × 인용문헌 하나에 대한 모델 판정과, 대조를 통과한 근거."""

    judgment: Judgment
    picks: list[tuple[_Candidate, str]] = field(default_factory=list)  # (후보, 조각 원문 글자)
    dropped: int = 0  # 대조에 떨어져 버린 근거 수


@dataclass
class _Collected:
    """단위 하나를 도는 동안 쌓는 기록."""

    held: list[HeldTask] = field(default_factory=list)
    search_log: list[SearchLogRow] = field(default_factory=list)
    examiner: list[ExaminerLocationRow] = field(default_factory=list)


# ---- 1) 후보 모으기: 검색 상위 k ∪ 심사관 지정 조각 ----
def _log_status(result: SearchResult, scope: str) -> Status:
    if result.hits:
        return _confirmed("검색 결과를 받음")
    if result.status == "not_found_in_scope":
        return Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
    return _unverified(UnverifiedReason.BODY_MISSING)


def _gather(
    unit: JudgmentUnit,
    claim: int,
    elements: list[ClaimElement],
    cites: list[ResolvedCitation],
    oa: OAResult,
    config: F3Config,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
) -> dict[str, _Candidate]:
    settings = config.settings
    search = settings.search
    mode = search.impl if search.impl in _MODES else "hybrid"
    candidates: dict[str, _Candidate] = {}
    for e in elements:
        for cite in cites:
            # 질의는 구성요소 원문뿐이다 (심사관 지정 번호를 넣지 않는다). 범위는 그 인용문헌 하나
            result = searcher.search(e.text, "cite", mode, search.k, doc_ids=[cite.doc_id])
            scope = _scope_text(cite, settings)
            seen.search_log.append(
                SearchLogRow(
                    unit_id=unit.unit_id,
                    claim=claim,
                    element_no=e.no,
                    element_hash=hashlib.sha256(e.text.encode("utf-8")).hexdigest()[:12],
                    citation=cite.label,
                    doc_id=cite.doc_id,
                    status=_log_status(result, scope),
                    searched_scope=scope,
                    hit_chunk_ids=[h.chunk_id for h in result.hits],
                )
            )
            for hit in result.hits:
                found = candidates.setdefault(hit.chunk_id, _Candidate(hit, cite.label))
                found.ranks[e.no] = hit.rank
    if not settings.use_examiner_paragraphs:
        return candidates  # 평가 누출 막기: 심사관 위치를 읽지도 않는다
    for cite in cites:
        locations = examiner_locations(oa, unit.rejection, claim, cite.label)
        if not locations:
            continue
        doc_chunks = {
            c.chunk_id: c for c in repo.chunks("cite", search.index_version, [cite.doc_id])
        }
        for location in locations:
            match = match_location(location, list(doc_chunks.values()))
            seen.examiner.append(
                ExaminerLocationRow(
                    unit_id=unit.unit_id,
                    claim=claim,
                    citation=cite.label,
                    location=location,
                    chunk_ids=match.chunk_ids,
                    status=match.status,
                )
            )
            for chunk_id in match.chunk_ids:
                found = candidates.setdefault(
                    chunk_id, _Candidate(doc_chunks[chunk_id], cite.label)
                )
                found.examiner = True
    return candidates


# ---- 2) 모델 답을 후보 조각과 대조 ----
def _check(
    answer: CompareAnswer,
    claim: int,
    element_nos: list[int],
    labels: list[str],
    candidates: Mapping[str, _Candidate],
) -> tuple[dict[tuple[int, str], _Judged], list[str]]:
    errors: list[str] = []
    if answer.claim != claim:
        errors.append(f"claim은 {claim}이어야 함 (받은 값 {answer.claim})")
    judged: dict[tuple[int, str], _Judged] = {}
    for i, row in enumerate(answer.rows):
        key = (row.element_no, row.citation)
        if row.element_no not in element_nos or row.citation not in labels:
            errors.append(f"rows[{i}]: 없는 구성요소 번호나 인용문헌 {key}")
            continue
        if key in judged:
            errors.append(f"rows[{i}]: {key} 줄이 둘 이상")
            continue
        one = _Judged(row.judgment)
        for pick in row.evidence:
            found = candidates.get(pick.chunk_id)
            if found is None or found.label != row.citation:
                errors.append(f"rows[{i}]: 후보에 없는 chunk_id {pick.chunk_id!r}")
                one.dropped += 1
                continue
            # 근거 글자가 그 조각 글에 그대로 있는지 (공백 줄이기만 허용)
            span = find_span(pick.quote, found.chunk.text)
            if span is None:
                errors.append(
                    f"rows[{i}]: quote가 {pick.chunk_id} 글에 그대로 없음: {pick.quote!r}"
                )
                one.dropped += 1
                continue
            one.picks.append((found, found.chunk.text[span[0] : span[1]]))
        if row.judgment == Judgment.DISCLOSED and not row.evidence:
            errors.append(f"rows[{i}]: disclosed인데 evidence가 없음")
        judged[key] = one
    missing = [(n, label) for n in element_nos for label in labels if (n, label) not in judged]
    if missing:
        errors.append(f"rows에 빠진 (구성요소 번호, 인용문헌): {missing}")
    return judged, errors


_RETRY_NOTE = (
    "\n앞 답이 검사에 떨어졌습니다. 아래 오류를 고쳐 같은 형식으로 다시 답하세요.\n"
    "검사 오류:\n{error}\n"
)
_MAX_ERROR_CHARS = 2000  # 오류 문구가 길면 앞부분만


def _ask(
    claim: int,
    claim_text: str,
    elements: list[ClaimElement],
    labels: list[str],
    candidates: Mapping[str, _Candidate],
    ctx: RunContext,
) -> dict[tuple[int, str], _Judged]:
    """모델 1회. 형식이나 대조 검사에 떨어지면 검사 오류를 붙여 한 번만 더 부른다.

    두 번째 답도 형식(JSON·스키마)이 틀리면 ModelOutputInvalid를 그대로 던진다.
    """
    shown = sorted(candidates.values(), key=lambda c: (c.label, c.chunk.chunk_id))
    variables = {
        "claim": str(claim),
        "citations": ", ".join(labels),
        "claim_text": claim_text,
        "elements": "\n".join(f"{e.no}: {' '.join(e.text.split())}" for e in elements),
        # 후보에는 심사관 지정 여부도 검색 순위도 싣지 않는다
        "candidates": json.dumps(
            [
                {"chunk_id": c.chunk.chunk_id, "citation": c.label, "text": c.chunk.text}
                for c in shown
            ],
            ensure_ascii=False,
            indent=1,
        ),
        "retry_note": "",
    }
    element_nos = [e.no for e in elements]
    try:
        first = call_model(STEP, variables, CompareAnswer, ctx=ctx, attempt=1)
        judged, errors = _check(first.parsed, claim, element_nos, labels, candidates)
        if not errors:
            return judged
        error = "\n".join(errors)
    except ModelOutputInvalid as e:
        error = str(e)
    logger.warning("compare 청구항 %d: 답이 검사에 떨어져 검사 오류를 붙여 한 번 더 부름", claim)
    variables["retry_note"] = _RETRY_NOTE.format(error=error[:_MAX_ERROR_CHARS])
    second = call_model(STEP, variables, CompareAnswer, ctx=ctx, attempt=2)
    judged, errors = _check(second.parsed, claim, element_nos, labels, candidates)
    if errors:
        logger.warning(
            "compare 청구항 %d: 다시 불러도 검사 오류 %d건 (틀린 근거는 버리고 상태를 낮춤)",
            claim,
            len(errors),
        )
    return judged


# ---- 3) 줄 만들기 ----
def _evidence(found: _Candidate, raw_text: str) -> Evidence:
    chunk = found.chunk
    return Evidence(
        document_id=chunk.doc_id,
        location=chunk.location.label,
        raw_text=raw_text,
        chunk_id=chunk.chunk_id,
        index_version=chunk.index_version,
    )


def _why(element_no: int, picks: list[tuple[_Candidate, str]], scope: str) -> str:
    """AI가 찾은 문단을 왜 가져왔나 (어떤 질의·검색에서 몇 위였나)."""
    ranks = [found.ranks.get(element_no) for found, _ in picks]
    told = ", ".join(f"{r}위" if r else "다른 구성요소의 검색 결과" for r in ranks)
    return f"구성요소 글자를 질의로 검색 ({scope}): {told}"


def _rows_of(
    e: ClaimElement,
    cite: ResolvedCitation,
    one: _Judged | None,
    settings: F3Settings,
) -> list[ComparisonRow]:
    """구성요소 × 인용문헌 하나의 줄. 근거 출처가 섞이면 심사관 지정 / AI 찾음 두 줄로 나눈다."""
    scope = _scope_text(cite, settings)

    def row(judgment: Judgment, status: Status, picks=(), examiner=False, why=None):
        return ComparisonRow(
            claim=e.claim,
            element=e.text,
            element_location=e.element_location,
            citation=cite.label,
            judgment=judgment,
            paragraph_source=ParagraphSource.EXAMINER if examiner else ParagraphSource.AI_FOUND,
            why_retrieved=None if examiner else why,
            status=status,
            evidence=[_evidence(found, text) for found, text in picks],
        )

    if e.status.value != StatusValue.CONFIRMED:
        why = "구성요소 글자를 청구항 원문에서 확인하지 못해 찾지 않음"
        return [row(Judgment.UNCLEAR, _unverified(UnverifiedReason.INPUT_UNVERIFIED), why=why)]
    if one is None:
        why = "모델이 이 구성요소 × 인용문헌 판정을 주지 않음"
        return [row(Judgment.UNCLEAR, _unverified(UnverifiedReason.NOT_EXTRACTED), why=why)]
    if not one.picks:
        if one.dropped or one.judgment == Judgment.DISCLOSED:
            # 근거가 대조에 다 떨어졌거나 근거 없이 개시됨이라고 함: 판정을 싣지 않는다
            why = "모델이 준 근거가 후보 조각과 맞지 않아 뺌"
            status = _unverified(UnverifiedReason.EVIDENCE_REJECTED)
            return [row(Judgment.UNCLEAR, status, why=why)]
        # 못 찾음: 없다고 단정하지 않고 찾아본 범위를 남긴다
        status = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
        why = f"구성요소 글자를 질의로 검색 ({scope}): AI가 근거로 고른 문단이 없음"
        return [row(one.judgment, status, why=why)]
    status = (
        _unverified(UnverifiedReason.EVIDENCE_REJECTED)
        if one.dropped
        else _confirmed("근거 글자가 인용문헌 조각에 그대로 있음")
    )
    by_examiner = [p for p in one.picks if p[0].examiner]
    by_ai = [p for p in one.picks if not p[0].examiner]
    rows = []
    if by_examiner:
        rows.append(row(one.judgment, status, by_examiner, examiner=True))
    if by_ai:
        rows.append(row(one.judgment, status, by_ai, why=_why(e.no, by_ai, scope)))
    return rows


def _compare_claim(
    unit: JudgmentUnit,
    split: SplitClaim,
    cites: list[ResolvedCitation],
    oa: OAResult,
    config: F3Config,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
) -> list[ComparisonRow]:
    claim = split.claim
    # 원문에서 확인된 구성요소만 찾고 판정한다
    usable = [e for e in split.elements if e.status.value == StatusValue.CONFIRMED]
    labels = [c.label for c in cites]
    candidates = _gather(unit, claim, usable, cites, oa, config, searcher, repo, seen)
    judged: dict[tuple[int, str], _Judged] = {}
    if usable and candidates:
        claim_text = config.inputs.claims_at_oa.get(claim, "")
        judged = _ask(claim, claim_text, usable, labels, candidates, ctx)
    elif usable:
        # 후보가 하나도 없으면 모델을 부르지 않는다: 모두 "조회 범위 내 없음"
        logger.warning("compare 청구항 %d: 후보 조각이 0개라 모델을 부르지 않음", claim)
        judged = {
            (e.no, label): _Judged(Judgment.DIFFERENCE_CANDIDATE)
            for e in usable
            for label in labels
        }
    rows: list[ComparisonRow] = []
    for e in split.elements:
        for cite in cites:
            rows += _rows_of(e, cite, judged.get((e.no, cite.label)), config.settings)
    return rows


# ---- 4) 요약 (줄 판정을 모은 표시일 뿐, 판정이 아니다) ----
def _element_marks(rows: list[ComparisonRow]) -> dict[tuple[int, str], tuple[str, Judgment]]:
    """구성요소(청구항, 위치)마다 (글자, 모은 판정). 개시됨 줄이 하나라도 있으면 개시됨."""
    order = [Judgment.DISCLOSED, Judgment.DIFFERENCE_CANDIDATE, Judgment.UNCLEAR]
    marks: dict[tuple[int, str], tuple[str, Judgment]] = {}
    for r in rows:
        if r.status.reason == UnverifiedReason.INPUT_UNVERIFIED and not r.evidence:
            continue  # 원문에서 확인 못 한 구성요소는 요약에 넣지 않는다
        key = (r.claim, r.element_location)
        old = marks.get(key)
        if old is None or order.index(r.judgment) < order.index(old[1]):
            marks[key] = (r.element, r.judgment)
    return marks


def _inventive_summary(rows: list[ComparisonRow], rej: Rejection) -> InventiveSummary:
    marks = _element_marks(rows)
    # 차이점: 대비한 어느 문헌에서도 개시됨 줄이 없는 구성요소
    differences = [
        f"{location} {text}"
        for (_, location), (text, mark) in marks.items()
        if mark != Judgment.DISCLOSED
    ]
    reasoning = rej.examiner_reasoning
    logger.warning(
        "compare 거절이유 %d: 효과 후보는 아직 뽑지 않음 (빈 목록, 직접 검토 필요)", rej.no
    )
    return InventiveSummary(
        kind="inventive_step",
        differences=differences,
        combination=reasoning.value or reasoning.raw_text or "심사관 결합 논리 확인되지 않음",
        effect_candidates=[],
    )


def _novelty_summary(rows: list[ComparisonRow], unit: JudgmentUnit, label: str) -> NoveltySummary:
    marks = _element_marks(rows)
    names = {
        Judgment.DISCLOSED: "개시됨",
        Judgment.DIFFERENCE_CANDIDATE: "차이 후보",
        Judgment.UNCLEAR: "불명",
    }
    told = []
    for claim in sorted({c for c, _ in marks}):
        mine = [mark for (c, _), (_, mark) in marks.items() if c == claim]
        counts = ", ".join(f"{name} {mine.count(j)}" for j, name in names.items())
        told.append(f"청구항 {claim}: 구성요소 {len(mine)}개 중 {counts}")
    # 표시는 대표 청구항의 줄로 정한다 (대표 청구항 줄이 없으면 모든 줄)
    rep = unit.representative_claim
    basis = [mark for (c, _), (_, mark) in marks.items() if c == rep] or [
        mark for _, mark in marks.values()
    ]
    if basis and all(m == Judgment.DISCLOSED for m in basis):
        verdict = NoveltyVerdict.NO_DIFFERENCE
    elif Judgment.DIFFERENCE_CANDIDATE in basis:
        verdict = NoveltyVerdict.DIFFERENT
    else:
        verdict = NoveltyVerdict.SUBSTANTIALLY_SAME_CANDIDATE
    reason = f"AI 정리, 판정 아님 (대표 청구항 {rep}의 줄 판정을 모은 표시). " + "; ".join(told)
    return NoveltySummary(kind="novelty", citation=label, verdict=verdict, reason=reason)


# ---- 단위 하나 ----
def _labels_for(oa: OAResult, rejection_no: int, claim: int, group: list[ResolvedCitation]):
    """그 청구항에 심사관이 적용한 인용문헌만. 청구항 줄이 없거나 인용이 비면 묶음 전부."""
    row = find_claim_row(oa, rejection_no, claim)
    if row is None or not row.citations:
        return group
    return [c for c in group if c.label in row.citations]


def _hold(seen: _Collected, task: str, waiting_for: str) -> None:
    if all(h.task != task for h in seen.held):
        seen.held.append(HeldTask(task=task, waiting_for=waiting_for))


def compare_unit(
    unit: JudgmentUnit,
    oa: OAResult,
    splits: Mapping[int, SplitClaim],
    config: F3Config,
    *,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
) -> CompareOutput:
    """진보성·신규성 판단 단위 하나를 대비한다.

    searcher·repo는 데이터가 아니라 객체라 설정 모델 밖 인자로 받는다 (make_searcher로 만든다).
    진보성은 표 하나, 신규성은 대비할 수 있는 인용문헌마다 표 하나(같은 unit_id)를 만든다.
    """
    if unit.rejection_kind not in (RejectionKind.INVENTIVE_STEP, RejectionKind.NOVELTY):
        raise ValueError(f"대비 단계는 진보성·신규성 단위만 받는다: {unit.unit_id}")
    rej = next(r for r in oa.rejections if r.no == unit.rejection)
    settings = config.settings
    seen = _Collected()
    resolved = resolve_citations(rej, oa.oa_id, repo, settings.search.index_version)
    for r in resolved:
        if r.held_task is not None:
            _hold(seen, r.held_task.task, r.held_task.waiting_for)
    usable = [r for r in resolved if r.compared.compared]
    skipped = [r.compared for r in resolved if not r.compared.compared]
    tables: list[ComparisonTable] = []
    if not usable:
        logger.warning("compare %s: 대비할 수 있는 인용문헌이 없어 표를 만들지 않음", unit.unit_id)
        _hold(seen, f"f3_compare:{unit.unit_id}", "대비할 수 있는 인용문헌 (본문 확보·직접 확인)")

    novelty = unit.rejection_kind == RejectionKind.NOVELTY
    # 신규성은 인용문헌 하나씩 따로 (두 문헌을 한 프롬프트·한 표에 섞지 않는다)
    groups = [[c] for c in usable] if novelty else ([usable] if usable else [])
    input_ok = config.inputs.claims_status.value == StatusValue.CONFIRMED
    for group in groups:
        rows: list[ComparisonRow] = []
        for claim in unit.claims:
            split = splits.get(claim)
            if split is None or not split.elements:
                logger.warning(
                    "compare %s: 청구항 %d의 구성요소가 없어 건너뜀", unit.unit_id, claim
                )
                _hold(
                    seen,
                    f"f3_compare:{unit.unit_id}:claim{claim}",
                    f"청구항 {claim} 구성요소 나누기",
                )
                continue
            cites = _labels_for(oa, unit.rejection, claim, group)
            if cites:
                rows += _compare_claim(unit, split, cites, oa, config, ctx, searcher, repo, seen)
        if not input_ok:
            # OA 당시 청구항 판이 확인되지 않았으면 뒤 결과는 모두 input_unverified
            bad = _unverified(UnverifiedReason.INPUT_UNVERIFIED)
            rows = [r.model_copy(update={"status": bad}) for r in rows]
        if not rows:
            labels = "·".join(c.label for c in group)
            logger.warning("compare %s: %s 대비 줄이 0개라 표를 만들지 않음", unit.unit_id, labels)
            _hold(seen, f"f3_compare:{unit.unit_id}:{labels}", "대비할 청구항 구성요소")
            continue
        summary = (
            _novelty_summary(rows, unit, group[0].label)
            if novelty
            else _inventive_summary(rows, rej)
        )
        # 직접 검토 필요: 대비 안 한 인용이 있음 / 효과 후보를 안 뽑음(진보성) /
        # 단위 묶음이 확인 안 됨
        review = bool(skipped) or not novelty or unit.status.value != StatusValue.CONFIRMED
        tables.append(
            ComparisonTable(
                unit_id=unit.unit_id,
                rejection_kind=unit.rejection_kind,
                citations=[c.compared for c in group] + skipped,
                rows=rows,
                summary=summary,
                status=summarize_table_status(rows),
                flags=[Flag.NEEDS_HUMAN_REVIEW] if review else [],
            )
        )
    return CompareOutput(
        tables=tables,
        held_tasks=seen.held,
        search_log=seen.search_log,
        examiner_locations=seen.examiner,
    )


def compare_units(
    units: list[JudgmentUnit],
    oa: OAResult,
    splits: Mapping[int, SplitClaim],
    config: F3Config,
    *,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
) -> CompareOutput:
    """진보성·신규성 단위를 순서대로 대비해 한데 모은다 (명확성 단위는 건너뛴다)."""
    total = _Collected()
    tables: list[ComparisonTable] = []
    for unit in sorted(units, key=lambda u: u.order):
        if unit.rejection_kind == RejectionKind.CLARITY:
            continue
        out = compare_unit(unit, oa, splits, config, ctx=ctx, searcher=searcher, repo=repo)
        tables += out.tables
        total.search_log += out.search_log
        total.examiner += out.examiner_locations
        for h in out.held_tasks:
            _hold(total, h.task, h.waiting_for)
    if not tables:
        logger.warning("compare %s: 대비표가 0개", oa.oa_id)
    return CompareOutput(
        tables=tables,
        held_tasks=total.held,
        search_log=total.search_log,
        examiner_locations=total.examiner,
    )
