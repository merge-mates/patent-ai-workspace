"""진보성·신규성 대비 단계 (F3 ②③): 판단 단위 하나 -> ComparisonTable.

청구항마다: 구성요소 글자를 질의로 인용문헌 안에서 검색(상위 k) -> 모델 1회가 구성요소 × 후보 문단을
판정 -> 코드가 근거를 후보 조각과 대조 -> 줄(ComparisonRow)을 만든다.
- 검색 질의는 구성요소 원문뿐이다. 심사관이 짚은 위치는 질의에 절대 넣지 않는다.
- 심사관 지정 조각은 (설정이 켜져 있을 때만) 표시 없이 후보에 더하고, 줄의 출처는 코드가 붙인다.
- 근거를 못 고르면 "조회 범위 내 없음" + 찾아본 범위. "없다"고 단정하는 글을 만들지 않는다.
- 신규성은 인용문헌 하나와만: 인용문헌마다 모델을 따로 부르고 표도 따로 만든다.
- 종속항 대비에는 그 종속항이 인용하는(거슬러 올라가는) 부모 청구항의 구성요소를 같이 넣는다
  (11/21 결정). 줄의 claim은 대비 대상 종속항, element_location은 구성요소가 실제로 있는 청구항이다.
  부모가 같은 단위 안에서 이미 대비되면 다시 넣지 않는다.
- 같은 (질의, 인용문헌) 검색은 한 번만 한다 (부모 구성요소가 종속항마다 되풀이되므로).
"""

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
from patent_ai.core.f3_claim_compare.retry import call_checked, confirmed, unverified
from patent_ai.core.f3_claim_compare.textmatch import find_span, is_too_short, text_hash
from patent_ai.core.f3_claim_compare.units import ancestors
from patent_ai.core.llm.embed import query_embedder
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import (
    Evidence,
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
)
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
def _mode(impl: str) -> str:
    """검색 구현 이름 -> 검색 방식. 모르는 이름을 조용히 hybrid로 바꾸지 않는다."""
    if impl not in _MODES:
        raise ModelConfigError(
            f"config/f3.yaml search.impl {impl!r}은 대비 단계가 모르는 검색 방식 (가능: {_MODES})"
        )
    return impl


def _scope_text(cite: ResolvedCitation, settings: F3Settings) -> str:
    """찾아본 범위를 사람이 읽는 글로."""
    s = settings.search
    return f"{cite.label} 조각 {cite.chunk_count}개 중 {s.impl} 상위 {s.k} ({s.index_version})"


@dataclass
class _Item:
    """대비할 구성요소 하나. n은 모델에게 보여 주는 번호 (청구항 안 순번이 아니라 목록 순번)."""

    n: int
    e: ClaimElement


@dataclass
class _View:
    """청구항 하나(대비 대상)의 대비 목록: 부모에서 온 구성요소 + 자기 구성요소."""

    claim: int
    items: list[_Item]
    # 모델에 보여 줄 청구항 글자 (부모에서 온 구성요소가 있으면 그 부모 청구항 글자도)
    claim_text: str
    parents: list[int] = field(default_factory=list)  # 구성요소를 빌려 온 부모 청구항
    # 빌려 올 부모의 나누기 결과가 비었거나 확인되지 않음: 표를 input_unverified로 둔다
    parent_unverified: bool = False
    # 인용 가지가 여럿("제2항 또는 제3항")인데 빌려야 할 부모가 남아 못 빌림 (보류를 만든다)
    branch_blocked: bool = False


def _has_branch(claim: int, splits: Mapping[int, SplitClaim]) -> bool:
    """인용 경로 어디엔가 앞 청구항을 둘 이상 인용하는 청구항("제2항 또는 제3항")이 있나."""
    seen: set[int] = set()
    todo = [claim]
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.add(c)
        depends = splits[c].depends_on or []
        if len(depends) > 1:
            return True
        todo += depends
    return False


def _carried_parents(
    claim: int,
    compared: Mapping[int, set[str]],
    labels: set[str],
    splits: Mapping[int, SplitClaim],
) -> tuple[list[int], bool]:
    """(구성요소를 빌려 와야 하는 부모 청구항들(번호 순), 가지 때문에 못 빌렸는지).

    인용을 거슬러 올라간 앞 청구항 중, 이 묶음에서 이미 대비되는 청구항(과 그 앞 청구항들)은 뺀다.
    "이미 대비됨" = 그 부모가 이 묶음에 있고 이 종속항이 대비되는 문헌을 모두 대비받음
    (신규성은 문헌마다 표가 따로라, 부모가 다른 문헌과 대비됐다고 이 문헌 대비를 건너뛰면 안 된다).
    인용 관계를 모르는 청구항(ancestors가 None)이면 아무것도 빌리지 않는다: 단위가
    확인되지 않음으로 남고 대비표에도 자기 구성요소만 들어간다.
    """
    family = ancestors(claim, splits)
    if not family:
        return [], False
    covered: set[int] = set()
    for a in family:
        if splits[a].elements and labels <= compared.get(a, set()):
            covered |= {a} | (ancestors(a, splits) or set())
    need = sorted(family - covered)
    if need and _has_branch(claim, splits):
        # 가지마다 따로 대비하는 일은 아직 없다. 가지 합집합을 한 청구항처럼 대비하지 않고,
        # 부모 없이 확인됨으로 나가지 않게 "못 빌림"으로 알린다 (부모가 이미 대비됐으면 통과)
        logger.warning(
            "compare 청구항 %d: 인용 가지가 여럿이라 부모 구성요소를 넣지 않음 (직접 검토 필요)",
            claim,
        )
        return [], True
    return need, False


def _make_view(
    split: SplitClaim,
    compared: Mapping[int, set[str]],
    splits: Mapping[int, SplitClaim],
    config: F3Config,
) -> _View:
    texts = config.inputs.claims_at_oa
    parents, blocked = _carried_parents(split.claim, compared, compared[split.claim], splits)
    unverified_parent = blocked
    for p in parents:
        if not splits[p].elements or splits[p].status.value != StatusValue.CONFIRMED:
            # 조용히 빠지지 않게: 경고를 남기고 표를 확인되지 않음으로 둔다
            logger.warning(
                "compare 청구항 %d: 부모 청구항 %d의 구성요소 나누기가 비었거나 확인되지 않아"
                " 부모 구성요소를 온전히 대비하지 못함",
                split.claim,
                p,
            )
            unverified_parent = True
    elements = [e for p in parents for e in splits[p].elements] + list(split.elements)
    items = [_Item(n, e) for n, e in enumerate(elements, start=1)]
    if parents:
        shown = [f"[청구항 {p}: 인용되는 앞 청구항]\n{texts.get(p, '')}" for p in parents]
        shown.append(f"[청구항 {split.claim}: 대비 대상]\n{texts.get(split.claim, '')}")
        claim_text = "\n\n".join(shown)
    else:
        claim_text = texts.get(split.claim, "")
    return _View(split.claim, items, claim_text, parents, unverified_parent, blocked)


class _CachedSearcher:
    """같은 검색(질의·말뭉치·방식·k·문헌)은 한 번만 하고 결과를 다시 쓴다."""

    def __init__(self, inner: Searcher):
        self.inner = inner
        self.done: dict[tuple, SearchResult] = {}

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None):
        key = (query, corpus, mode, k, tuple(doc_ids or ()), as_of)
        if key not in self.done:
            self.done[key] = self.inner.search(query, corpus, mode, k, doc_ids=doc_ids, as_of=as_of)
        return self.done[key]


def _cached(searcher: Searcher) -> Searcher:
    return searcher if isinstance(searcher, _CachedSearcher) else _CachedSearcher(searcher)


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
    scope: str | None = None  # 한 번 더 찾았을 때의 찾아본 범위 글 (두 번 찾음)

    def not_found(self) -> bool:
        """근거를 못 고른 것 (버린 근거도 없고 개시됨이라고 하지도 않음)."""
        return not self.picks and not self.dropped and self.judgment != Judgment.DISCLOSED


@dataclass
class _Collected:
    """단위 하나를 도는 동안 쌓는 기록."""

    held: list[HeldTask] = field(default_factory=list)
    search_log: list[SearchLogRow] = field(default_factory=list)
    examiner: list[ExaminerLocationRow] = field(default_factory=list)


# ---- 1) 후보 모으기: 검색 상위 k ∪ 심사관 지정 조각 ----
def _log_status(result: SearchResult, scope: str) -> Status:
    if result.hits:
        return confirmed("검색 결과를 받음")
    if result.status == "not_found_in_scope":
        return Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
    return unverified(UnverifiedReason.BODY_MISSING)


def _gather(
    unit: JudgmentUnit,
    claim: int,
    items: list[_Item],
    cites: list[ResolvedCitation],
    oa: OAResult,
    config: F3Config,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
) -> dict[str, _Candidate]:
    settings = config.settings
    search = settings.search
    mode = _mode(search.impl)
    candidates: dict[str, _Candidate] = {}
    for item in items:
        e = item.e
        for cite in cites:
            # 질의는 구성요소 원문뿐이다 (심사관 지정 번호를 넣지 않는다). 범위는 그 인용문헌 하나
            result = searcher.search(e.text, "cite", mode, search.k, doc_ids=[cite.doc_id])
            scope = _scope_text(cite, settings)
            seen.search_log.append(
                SearchLogRow(
                    unit_id=unit.unit_id,
                    claim=claim,
                    element_claim=e.claim,
                    element_no=e.no,
                    element_hash=text_hash(e.text),
                    citation=cite.label,
                    doc_id=cite.doc_id,
                    status=_log_status(result, scope),
                    searched_scope=scope,
                    hit_chunk_ids=[h.chunk_id for h in result.hits],
                )
            )
            for hit in result.hits:
                found = candidates.setdefault(hit.chunk_id, _Candidate(hit, cite.label))
                found.ranks[item.n] = hit.rank
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
    pairs: list[tuple[int, str]],
    candidates: Mapping[str, _Candidate],
    min_chars: int,
) -> tuple[dict[tuple[int, str], _Judged], list[str]]:
    """pairs: 판정을 받아야 하는 (구성요소 번호, 인용문헌). 그 밖의 줄은 받지 않는다."""
    element_nos = {n for n, _ in pairs}
    labels = {label for _, label in pairs}
    errors: list[str] = []
    if answer.claim != claim:
        errors.append(f"claim은 {claim}이어야 함 (받은 값 {answer.claim})")
    judged: dict[tuple[int, str], _Judged] = {}
    for i, row in enumerate(answer.rows):
        key = (row.element_no, row.citation)
        if row.element_no not in element_nos or row.citation not in labels:
            errors.append(f"rows[{i}]: 없는 구성요소 번호나 인용문헌 {key}")
            continue
        if key not in pairs:
            continue  # 묻지 않은 짝 (한 번 더 찾기에서 이미 찾은 것): 조용히 넘긴다
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
            # 한두 글자는 아무 조각에나 맞아 근거가 되지 못한다 (조각 전체를 옮긴 것은 받음)
            if is_too_short(pick.quote, found.chunk.text, min_chars):
                errors.append(f"rows[{i}]: quote가 너무 짧음 ({min_chars}자 이상): {pick.quote!r}")
                one.dropped += 1
                continue
            one.picks.append((found, found.chunk.text[span[0] : span[1]]))
        if row.judgment == Judgment.DISCLOSED and not row.evidence:
            errors.append(f"rows[{i}]: disclosed인데 evidence가 없음")
        judged[key] = one
    missing = [pair for pair in pairs if pair not in judged]
    if missing:
        errors.append(f"rows에 빠진 (구성요소 번호, 인용문헌): {missing}")
    return judged, errors


def _item_line(item: _Item, claim: int) -> str:
    """모델에 보여 줄 구성요소 한 줄. 부모 청구항에서 온 것은 어느 청구항 것인지 덧붙인다."""
    line = f"{item.n}: {' '.join(item.e.text.split())}"
    return line if item.e.claim == claim else f"{line} (청구항 {item.e.claim}의 구성요소)"


def _ask(
    claim: int,
    claim_text: str,
    items: list[_Item],
    pairs: list[tuple[int, str]],
    candidates: Mapping[str, _Candidate],
    min_chars: int,
    ctx: RunContext,
) -> dict[tuple[int, str], _Judged]:
    """모델 1회. 형식이나 대조 검사에 떨어지면 검사 오류를 붙여 한 번만 더 부른다.

    틀린 근거는 _check가 버리고, 줄 status는 줄 만들기에서 낮춘다.
    """
    shown = sorted(candidates.values(), key=lambda c: (c.label, c.chunk.chunk_id))
    variables = {
        "claim": str(claim),
        "citations": ", ".join(dict.fromkeys(label for _, label in pairs)),
        "claim_text": claim_text,
        "elements": "\n".join(_item_line(i, claim) for i in items),
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

    def check(answer: CompareAnswer):
        return _check(answer, claim, pairs, candidates, min_chars)

    who = f"compare 청구항 {claim}"
    return call_checked(STEP, variables, CompareAnswer, check, ctx=ctx, who=who)


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


def _scope_text_twice(cite: ResolvedCitation, settings: F3Settings, figures: int) -> str:
    """두 번 찾아본 범위: 1차 상위 k, 이어서 상위 2k까지와 도면 설명 조각."""
    s = settings.search
    return (
        f"{cite.label} 조각 {cite.chunk_count}개 중 {s.impl} 상위 {s.k}, "
        f"이어서 상위 {settings.second_search_depth}까지와 도면 설명 조각 {figures}개 "
        f"({s.index_version}) · 두 번 찾음"
    )


def _rows_of(
    claim: int,
    item: _Item,
    cite: ResolvedCitation,
    one: _Judged | None,
    settings: F3Settings,
) -> list[ComparisonRow]:
    """구성요소 × 인용문헌 하나의 줄 (claim = 대비 대상 청구항).

    근거 출처가 섞이면 심사관 지정 / AI 찾음 두 줄로 나눈다.
    """
    e = item.e
    scope = (one.scope if one else None) or _scope_text(cite, settings)
    twice = one is not None and one.scope is not None

    def row(judgment: Judgment, status: Status, picks=(), examiner=False, why=None):
        return ComparisonRow(
            claim=claim,  # 부모에서 온 구성요소여도 줄의 claim은 대비 대상 종속항
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
        return [row(Judgment.UNCLEAR, unverified(UnverifiedReason.INPUT_UNVERIFIED), why=why)]
    if one is None:
        why = "모델이 이 구성요소 × 인용문헌 판정을 주지 않음"
        return [row(Judgment.UNCLEAR, unverified(UnverifiedReason.NOT_EXTRACTED), why=why)]
    if not one.picks:
        if one.dropped or one.judgment == Judgment.DISCLOSED:
            # 근거가 대조에 다 떨어졌거나 근거 없이 개시됨이라고 함: 판정을 싣지 않는다
            why = "모델이 준 근거가 후보 조각과 맞지 않아 뺌"
            status = unverified(UnverifiedReason.EVIDENCE_REJECTED)
            return [row(Judgment.UNCLEAR, status, why=why)]
        # 못 찾음: 없다고 단정하지 않고 찾아본 범위를 남긴다
        status = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
        why = f"구성요소 글자를 질의로 검색 ({scope}): AI가 근거로 고른 문단이 없음"
        return [row(one.judgment, status, why=why)]
    status = (
        unverified(UnverifiedReason.EVIDENCE_REJECTED)
        if one.dropped
        else confirmed("근거 글자가 인용문헌 조각에 그대로 있음")
    )
    by_examiner = [p for p in one.picks if p[0].examiner]
    by_ai = [p for p in one.picks if not p[0].examiner]
    rows = []
    if by_examiner:
        rows.append(row(one.judgment, status, by_examiner, examiner=True))
    if by_ai:
        why = _why(item.n, by_ai, scope)
        rows.append(row(one.judgment, status, by_ai, why="두 번째 검색. " + why if twice else why))
    return rows


# ---- 한 번 더 찾기 (second_search): 1차에서 근거를 못 고른 구성요소만 ----
def _second_log_status(result: SearchResult, fresh: bool, scope: str) -> Status:
    if fresh:
        return confirmed("두 번째 검색에서 새 조각을 받음")
    if result.status == "unverified":
        # 본문이 없어 못 찾은 것은 "조회 범위 내 없음"으로 덮지 않는다
        return _log_status(result, scope)
    return Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)


def _second_round(
    unit: JudgmentUnit,
    view: _View,
    missing: list[tuple[_Item, ResolvedCitation]],
    first: Mapping[tuple[int, str], Judgment],
    shown: Mapping[str, _Candidate],
    config: F3Config,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
) -> dict[tuple[int, str], _Judged]:
    """다른 문단·도면으로 한 번 더 찾는다.

    다른 문단 = 같은 질의로 더 깊이(설정 second_search_depth까지) 받아 1차에 보여 준 조각을 뺀 것.
    도면 = 그 인용문헌의 도면 설명 조각 가운데 1차에 안 보여 준 것.
    그래도 근거를 못 고르면 판정은 그대로 두고 두 번 찾아본 범위를 남긴다.
    """
    settings = config.settings
    search = settings.search
    mode = _mode(search.impl)
    claim = view.claim
    candidates: dict[str, _Candidate] = {}
    scopes: dict[str, str] = {}
    # 도면 설명 조각 (인용문헌마다 한 번만 읽는다)
    for cite in {c.label: c for _, c in missing}.values():
        figures = [
            c
            for c in repo.chunks("cite", search.index_version, [cite.doc_id])
            if c.chunk_kind == "figure_desc" and c.chunk_id not in shown
        ]
        for c in sorted(figures, key=lambda c: c.chunk_id):
            candidates[c.chunk_id] = _Candidate(c, cite.label)
        scopes[cite.label] = _scope_text_twice(cite, settings, len(figures))
    for item, cite in missing:
        e = item.e
        # 질의는 1차와 같다 (구성요소 원문뿐). 더 깊이 받아 이미 본 조각을 뺀다
        depth = settings.second_search_depth
        result = searcher.search(e.text, "cite", mode, depth, doc_ids=[cite.doc_id])
        fresh = [h for h in result.hits if h.chunk_id not in shown]
        scope = scopes[cite.label]
        seen.search_log.append(
            SearchLogRow(
                unit_id=unit.unit_id,
                claim=claim,
                element_claim=e.claim,
                element_no=e.no,
                element_hash=text_hash(e.text),
                citation=cite.label,
                doc_id=cite.doc_id,
                round=2,
                status=_second_log_status(result, bool(fresh), scope),
                searched_scope=scope,
                hit_chunk_ids=[h.chunk_id for h in fresh],
            )
        )
        for hit in fresh:
            found = candidates.setdefault(hit.chunk_id, _Candidate(hit, cite.label))
            found.ranks[item.n] = hit.rank
    pairs = [(item.n, cite.label) for item, cite in missing]
    again: dict[tuple[int, str], _Judged] = {}
    if candidates:
        items = list({i.n: i for i, _ in missing}.values())
        again = _ask(
            claim, view.claim_text, items, pairs, candidates, settings.min_quote_chars, ctx
        )
    else:
        logger.warning("compare 청구항 %d: 두 번째 검색에서 새 조각이 0개", claim)
    out: dict[tuple[int, str], _Judged] = {}
    for item, cite in missing:
        # 모델이 답을 안 준 짝은 1차 판정(못 찾음)을 그대로 두고 범위만 두 번으로 적는다
        one = again.get((item.n, cite.label)) or _Judged(first[(item.n, cite.label)])
        one.scope = scopes[cite.label]
        out[(item.n, cite.label)] = one
    return out


def _compare_claim(
    unit: JudgmentUnit,
    view: _View,
    cites: list[ResolvedCitation],
    oa: OAResult,
    config: F3Config,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
) -> list[ComparisonRow]:
    claim = view.claim
    # 원문에서 확인된 구성요소만 찾고 판정한다
    usable = [i for i in view.items if i.e.status.value == StatusValue.CONFIRMED]
    labels = [c.label for c in cites]
    candidates = _gather(unit, claim, usable, cites, oa, config, searcher, repo, seen)
    judged: dict[tuple[int, str], _Judged] = {}
    if usable and candidates:
        min_chars = config.settings.min_quote_chars
        pairs = [(i.n, label) for i in usable for label in labels]
        judged = _ask(claim, view.claim_text, usable, pairs, candidates, min_chars, ctx)
    elif usable:
        # 후보가 하나도 없으면 모델을 부르지 않는다: 모두 "조회 범위 내 없음"
        logger.warning("compare 청구항 %d: 후보 조각이 0개라 모델을 부르지 않음", claim)
        judged = {
            (i.n, label): _Judged(Judgment.DIFFERENCE_CANDIDATE) for i in usable for label in labels
        }
    if config.settings.second_search:
        missing = [
            (i, cite)
            for i in usable
            for cite in cites
            if (one := judged.get((i.n, cite.label))) is not None and one.not_found()
        ]
        if missing:
            first = {key: judged[key].judgment for key in [(i.n, c.label) for i, c in missing]}
            judged.update(
                _second_round(
                    unit, view, missing, first, candidates, config, ctx, searcher, repo, seen
                )
            )
    rows: list[ComparisonRow] = []
    for i in view.items:
        for cite in cites:
            rows += _rows_of(claim, i, cite, judged.get((i.n, cite.label)), config.settings)
    return rows


# ---- 4) 요약 (줄 판정을 모은 표시일 뿐, 판정이 아니다) ----
_Key = tuple[int, str]  # (청구항 번호, 구성요소 위치)
_LOST_NOTE = "(구성요소 글자를 확인하지 못해 대비하지 않음)"


def _element_marks(rows: list[ComparisonRow], lost: set[_Key]) -> dict[_Key, tuple[str, Judgment]]:
    """구성요소마다 (글자, 모은 판정). 개시됨 줄이 하나라도 있으면 개시됨.

    rows는 입력 상태로 status를 덮기 전의 줄이다 (줄 status로 거르지 않는다).
    원문에서 확인 못 한 구성요소(lost)는 대비하지 않았으므로 늘 불명으로 센다.
    """
    order = [Judgment.DISCLOSED, Judgment.DIFFERENCE_CANDIDATE, Judgment.UNCLEAR]
    marks: dict[_Key, tuple[str, Judgment]] = {}
    for r in rows:
        key = (r.claim, r.element_location)
        if key in lost:
            marks[key] = (r.element, Judgment.UNCLEAR)
            continue
        old = marks.get(key)
        if old is None or order.index(r.judgment) < order.index(old[1]):
            marks[key] = (r.element, r.judgment)
    return marks


def _status_note(rows: list[ComparisonRow], key: _Key, mark: Judgment) -> str:
    """차이점 글 뒤에 붙일 상태. 못 찾음 ≠ 없음이라, 근거 없는 차이 후보와 불명은 그대로 밝힌다.

    근거 있는 차이 후보 줄이 하나라도 있으면 꾸밈 없이 둔다 (덮기 전 줄로 본다).
    """
    if mark == Judgment.UNCLEAR:
        return " (불명)"
    mine = [
        r
        for r in rows
        if (r.claim, r.element_location) == key and r.judgment == Judgment.DIFFERENCE_CANDIDATE
    ]
    if any(r.evidence for r in mine):
        return ""
    # 찾아본 범위는 줄 status에 이미 있는 글을 그대로 쓴다 (문헌이 여럿이면 중복 없이 모은다)
    scopes = list(dict.fromkeys(r.status.searched_scope for r in mine if r.status.searched_scope))
    where = f": {'; '.join(scopes)}" if scopes else ""
    return f" (조회 범위 내 없음{where}, 없다는 판단 아님)"


def _inventive_summary(
    rows: list[ComparisonRow], lost: set[_Key], rej: Rejection, settings: F3Settings
) -> InventiveSummary:
    marks = _element_marks(rows, lost)
    # 차이점: 대비한 어느 문헌에서도 개시됨 줄이 없는 구성요소.
    # 확인 못 한 구성요소는 글자를 싣지 않고 대비하지 않았다고만 적는다 (빠뜨리지 않는다)
    differences = [
        f"{location} {_LOST_NOTE if (claim, location) in lost else text}"
        + ("" if (claim, location) in lost else _status_note(rows, (claim, location), mark))
        # 부모 청구항에서 온 구성요소는 어느 종속항 대비에서 왔는지 덧붙인다
        + ("" if location.startswith(f"청구항 {claim} ") else f" (청구항 {claim}에서 인용)")
        for (claim, location), (text, mark) in marks.items()
        if mark != Judgment.DISCLOSED
    ]
    reasoning = rej.examiner_reasoning
    if settings.use_examiner_paragraphs:
        combination = reasoning.value or reasoning.raw_text or "심사관 결합 논리 확인되지 않음"
    else:
        # 심사관 쪽 글을 쓰지 않는 실행: 결합 논리 원문도 싣지 않는다
        logger.warning("compare 거절이유 %d: 설정에 따라 심사관 결합 논리를 싣지 않음", rej.no)
        combination = "심사관 결합 논리를 싣지 않음 (use_examiner_paragraphs=false)"
    logger.warning(
        "compare 거절이유 %d: 효과 후보는 아직 뽑지 않음 (빈 목록, 직접 검토 필요)", rej.no
    )
    return InventiveSummary(
        kind="inventive_step",
        differences=differences,
        combination=combination,
        effect_candidates=[],
    )


def _differences_only_not_found(rows: list[ComparisonRow]) -> bool:
    """차이 후보 줄이 하나 이상 있고, 전부 근거 없이 "조회 범위 내 없음"인가 (덮기 전 줄로 본다)."""
    different = [r for r in rows if r.judgment == Judgment.DIFFERENCE_CANDIDATE]
    return bool(different) and all(
        r.status.value == StatusValue.NOT_FOUND_IN_SCOPE for r in different
    )


BRANCH_NOTE = "부모 청구항 구성요소를 대비하지 않음(인용 가지 여럿), 판단 아님"


def _novelty_summary(
    rows: list[ComparisonRow],
    lost: set[_Key],
    unit: JudgmentUnit,
    label: str,
    branch_blocked: frozenset[int] = frozenset(),
) -> NoveltySummary:
    marks = _element_marks(rows, lost)
    names = {
        Judgment.DISCLOSED: "개시됨",
        Judgment.DIFFERENCE_CANDIDATE: "차이 후보",
        Judgment.UNCLEAR: "불명",
    }
    told = []
    for claim in sorted({c for c, _ in marks}):
        mine = [mark for (c, _), (_, mark) in marks.items() if c == claim]
        counts = ", ".join(f"{name} {mine.count(j)}" for j, name in names.items())
        sentence = f"청구항 {claim}: 구성요소 {len(mine)}개 중 {counts}"
        if claim in branch_blocked:
            # 인용 가지가 여럿이라 부모 구성요소를 못 빌린 청구항: 부모를 대비하지 않았다고 밝힌다
            sentence += f". {BRANCH_NOTE}"
        told.append(sentence)
    # 표시는 대표 청구항의 줄로 정한다 (대표 청구항 줄이 없으면 모든 줄)
    rep = unit.representative_claim
    basis = [mark for (c, _), (_, mark) in marks.items() if c == rep] or [
        mark for _, mark in marks.values()
    ]
    reason = f"AI 정리, 판정 아님 (대표 청구항 {rep}의 줄 판정을 모은 표시). " + "; ".join(told)
    if basis and all(m == Judgment.DISCLOSED for m in basis):
        verdict = NoveltyVerdict.NO_DIFFERENCE
    elif Judgment.DIFFERENCE_CANDIDATE in basis:
        verdict = NoveltyVerdict.DIFFERENT
    else:
        # 스키마 세 값 중 남는 값이다. 실질적 동일이라고 본 것이 아님을 글로 분명히 한다
        verdict = NoveltyVerdict.SUBSTANTIALLY_SAME_CANDIDATE
        reason += ". 가리기 어려운 구성요소만 있음, 실질적 동일 판단 아님"
    if verdict == NoveltyVerdict.DIFFERENT and _differences_only_not_found(rows):
        # 못 찾음 ≠ 없음: 차이 후보가 전부 "조회 범위 내 없음" 줄에서만 나왔다
        reason += ". 차이 후보는 찾아본 범위에서 못 찾은 것, 없다는 판단 아님"
    lost_here = [key for key in marks if key in lost]
    if lost_here:
        reason += f". 확인 못 한 구성요소 {len(lost_here)}개 (대비하지 않음)"
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
    searcher = _cached(searcher)  # 같은 검색은 한 번만
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
    # 어느 묶음에서든 대비된 청구항 (신규성은 문헌마다 묶음이 따로라 합쳐서 본다)
    compared_anywhere: set[int] = set()
    for group in groups:
        rows: list[ComparisonRow] = []
        # 이 묶음(문헌)에서 청구항마다 대비하는 문헌. 부모가 "이미 대비됨"인지 문헌까지 따진다
        cites_of = {c: _labels_for(oa, unit.rejection, c, group) for c in unit.claims}
        has_elements = {c for c in unit.claims if c in splits and splits[c].elements}
        compared = {c: {x.label for x in cites_of[c]} for c in has_elements if cites_of[c]}
        compared_anywhere |= set(compared)
        # 청구항마다 대비 목록 (부모에서 온 구성요소 포함)
        views = {c: _make_view(splits[c], compared, splits, config) for c in compared}
        # 나누기에서 원문 위치를 못 정한 구성요소 (요약에서 불명으로 센다)
        lost: set[tuple[int, str]] = {
            (v.claim, i.e.element_location)
            for v in views.values()
            for i in v.items
            if i.e.status.value != StatusValue.CONFIRMED
        }
        for c, v in views.items():
            if v.branch_blocked:
                # 부모 없이 확인됨으로 나가지 않게: 줄은 input_unverified로 내리고 보류를 남긴다
                _hold(
                    seen,
                    f"f3_compare:{unit.unit_id}:claim{c}:branch",
                    "인용 가지마다 대비 (직접 검토 필요)",
                )
        for claim in unit.claims:
            if claim not in has_elements:
                logger.warning(
                    "compare %s: 청구항 %d의 구성요소가 없어 건너뜀", unit.unit_id, claim
                )
                _hold(
                    seen,
                    f"f3_compare:{unit.unit_id}:claim{claim}",
                    f"청구항 {claim} 구성요소 나누기",
                )
            elif claim in views:
                rows += _compare_claim(
                    unit, views[claim], cites_of[claim], oa, config, ctx, searcher, repo, seen
                )
        if not rows:
            labels = "·".join(c.label for c in group)
            logger.warning("compare %s: %s 대비 줄이 0개라 표를 만들지 않음", unit.unit_id, labels)
            _hold(seen, f"f3_compare:{unit.unit_id}:{labels}", "대비할 청구항 구성요소")
            continue
        unverified_claims = {c for c, v in views.items() if v.parent_unverified}
        # 요약은 status를 덮기 전의 줄로 모은다 (입력 상태 때문에 차이 후보가 빠지지 않게)
        summary = (
            _novelty_summary(
                rows,
                lost,
                unit,
                group[0].label,
                frozenset(c for c, v in views.items() if v.branch_blocked),
            )
            if novelty
            else _inventive_summary(rows, lost, rej, settings)
        )
        if unverified_claims:
            # 부모 구성요소를 온전히 대비하지 못한 종속항의 줄은 확인되지 않음으로 낮춘다
            bad = unverified(UnverifiedReason.INPUT_UNVERIFIED)
            rows = [
                r.model_copy(update={"status": bad}) if r.claim in unverified_claims else r
                for r in rows
            ]
        if not input_ok:
            # OA 당시 청구항 판이 확인되지 않았으면 뒤 결과는 모두 input_unverified
            bad = unverified(UnverifiedReason.INPUT_UNVERIFIED)
            rows = [r.model_copy(update={"status": bad}) for r in rows]
        # 대비표에는 늘 직접 검토 필요를 붙인다: 진보성은 효과 후보를 아직 뽑지 않았고,
        # 신규성 요약 표시는 AI 정리일 뿐이라 "차이 있음"도 결론처럼 읽히면 안 된다.
        # (대비 안 한 인용, 확인 안 된 단위도 이 표시로 사람에게 간다)
        tables.append(
            ComparisonTable(
                unit_id=unit.unit_id,
                rejection_kind=unit.rejection_kind,
                citations=[c.compared for c in group] + skipped,
                rows=rows,
                summary=summary,
                status=summarize_table_status(rows),
                flags=[Flag.NEEDS_HUMAN_REVIEW],
            )
        )
    # 구성요소는 있는데 어느 묶음에서도 대비되지 않은 청구항 (적용 문헌이 대비 불가이거나
    # 청구항 줄의 인용 라벨이 거절이유 인용 목록과 안 맞음): 기록 없이 빠지지 않게 보류한다
    if groups:
        for claim in unit.claims:
            if claim in splits and splits[claim].elements and claim not in compared_anywhere:
                logger.warning(
                    "compare %s: 청구항 %d에 적용된 대비할 수 있는 인용문헌이 없어 건너뜀",
                    unit.unit_id,
                    claim,
                )
                _hold(
                    seen,
                    f"f3_compare:{unit.unit_id}:claim{claim}",
                    f"청구항 {claim}에 적용된 대비할 수 있는 인용문헌"
                    " (인용 라벨·본문 확보 직접 확인)",
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
    searcher = _cached(searcher)  # 단위가 달라도 같은 (구성요소, 문헌) 검색은 한 번만
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
