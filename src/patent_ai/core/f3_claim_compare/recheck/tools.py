"""인용문헌 다시 찾기 도구 5개 (recheck design 4-1·4-2절).

search_bm25 · search_vector · open_paragraph · submit_evidence · give_up.
검색기와 조각 저장소만 부르고 모델은 부르지 않는다. 도구 검사 실패는 오류 결과(교정 지시)로 돌려주고
대화를 이어 가며, 검색 예외는 RecheckToolFailed로 올려 루프가 tool_failed로 끝내게 한다.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from patent_ai.core.agents.tool_loop import (
    GiveUp,
    RecheckToolFailed,
    ToolOutcome,
    ToolSpec,
)
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.schemas.comparison import Judgment
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Chunk

QUERY_MAX = 200  # 질의 글자 수 상한 [가정]
TRIED_MAX = 300  # give_up tried 글자 수 상한
SUBMIT_MIN, SUBMIT_MAX = 1, 5  # 한 번에 내는 문단 수
SEEN_NOTE = "(1차에 이미 봄)"
GIVE_UP_REASONS = ("not_in_document", "ambiguous_element", "need_figure", "other")


# ---- 도구 입력 (strict 스키마라 길이·범위 제약은 모델에 두지 않고 아래 코드가 다시 검사한다) ----
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchIn(_In):
    query: str
    k: int


class OpenIn(_In):
    paragraph_id: str


class SubmitCompareIn(_In):
    paragraph_ids: list[str]
    why: str


class EvidenceItem(_In):
    paragraph_id: str
    quote: str


class SubmitAgentIn(_In):
    items: list[EvidenceItem]
    judgment: Judgment
    why: str


class GiveUpIn(_In):
    reason: Literal["not_in_document", "ambiguous_element", "need_figure", "other"]
    tried: str


@dataclass(frozen=True)
class SubmittedItem:
    paragraph_id: str
    quote: str


@dataclass(frozen=True)
class Submitted:
    """submit_evidence가 검사를 통과했을 때의 끝 값. judge=compare면 items·judgment는 비어 있다."""

    paragraph_ids: list[str]
    why: str
    items: list[SubmittedItem] = field(default_factory=list)
    judgment: Judgment | None = None


def _squash(text: str) -> str:
    """공백을 모두 뺀 글 (quote가 문단에 그대로 있는지 볼 때 줄바꿈 차이를 무시)."""
    return re.sub(r"\s+", "", text)


def _error(content: str, **logged) -> ToolOutcome:
    return ToolOutcome(content, is_error=True, logged_input=logged)


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


class CiteToolbox:
    """인용문헌 하나(구성요소 하나를 찾는 대화 하나)의 도구 모음. 대화마다 새로 만든다."""

    def __init__(
        self,
        searcher: Searcher,
        repo: ChunkRepository,
        index_version: str,
        doc_id: str,
        label: str,
        exclude_ids: set[str],
        k_max: int,
        snippet_chars: int,
        *,
        root: Path | None = None,
    ) -> None:
        self.searcher = searcher
        self.repo = repo
        self.index_version = index_version
        self.doc_id = doc_id
        self.label = label
        self.exclude_ids = exclude_ids
        self.k_max = k_max
        self.snippet_chars = snippet_chars
        self.root = root or REPO_ROOT
        self.hits: list[str] = []  # 이 대화의 검색에 걸린 조각 ID (순서 유지, 중복 없음)
        self.opened: list[str] = []  # 연 문단 ID (순서 유지)
        # 받는 조각 범위 = 그 인용문헌 조각 + 이 대화의 검색 결과에 나온 조각 (design 4-1)
        self._doc_chunks: dict[str, Chunk] | None = None
        self._found: dict[str, Chunk] = {}

    # ---- 조각 찾기 ----
    def _own(self) -> dict[str, Chunk]:
        if self._doc_chunks is None:
            rows = self.repo.chunks("cite", self.index_version, [self.doc_id])
            self._doc_chunks = {c.chunk_id: c for c in rows}
        return self._doc_chunks

    def _get(self, chunk_id: str) -> Chunk | None:
        return self._own().get(chunk_id) or self._found.get(chunk_id)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """낸 조각 ID의 조각 (그 인용문헌 조각 또는 이 대화의 검색 결과). 없으면 None."""
        return self._get(chunk_id)

    def _neighbors(self, chunk: Chunk) -> tuple[str | None, str | None]:
        # 같은 종류 조각을 위치 순으로 늘어놓고 앞뒤 하나씩
        same = sorted(
            (c for c in self._own().values() if c.chunk_kind == chunk.chunk_kind),
            key=lambda c: (c.location.start is None, c.location.start or 0, c.chunk_id),
        )
        ids = [c.chunk_id for c in same]
        if chunk.chunk_id not in ids:
            return None, None
        i = ids.index(chunk.chunk_id)
        return (ids[i - 1] if i > 0 else None), (ids[i + 1] if i + 1 < len(ids) else None)

    # ---- 검색 ----
    def _search(self, mode: Literal["bm25", "vector"], m: SearchIn) -> ToolOutcome:
        logged = {"query": m.query, "k": m.k}
        if not m.query.strip() or len(m.query) > QUERY_MAX:
            return _error(f"query는 1~{QUERY_MAX}자 글이다. 짧게 줄여 다시 부른다", **logged)
        if not 1 <= m.k <= self.k_max:
            return _error(f"k는 1~{self.k_max} 정수다. 범위 안으로 고쳐 다시 부른다", **logged)
        try:
            result = self.searcher.search(m.query, "cite", mode, m.k, doc_ids=[self.doc_id])
        except ModelCallLimitExceeded:
            raise  # 질의 임베딩 호출 상한은 환경 실패가 아니다: 루프가 limit_reached로 끝낸다
        except Exception as e:  # 검색기·DB·임베딩 어떤 예외든 환경 실패로 본다
            raise RecheckToolFailed(f"{mode} 검색 실패: {type(e).__name__}: {e}") from e
        if not result.hits:
            return ToolOutcome("결과 0개: 다른 말로 찾거나 give_up", logged_input=logged)
        rows = []
        ids = []
        for h in result.hits:
            self._found[h.chunk_id] = h  # SearchHit은 Chunk의 하위 모양이라 그대로 둔다
            if h.chunk_id not in self.hits:
                self.hits.append(h.chunk_id)
            ids.append(h.chunk_id)
            row = {
                "rank": h.rank,
                "chunk_id": h.chunk_id,
                "location": h.location.label,
                "snippet": h.text[: self.snippet_chars],
            }
            if h.chunk_id in self.exclude_ids:
                row["note"] = SEEN_NOTE  # 1차에 이미 보여 준 조각: 빼지 않고 표시만
            rows.append(row)
        return ToolOutcome(_json(rows), result_ids=ids, logged_input=logged)

    # ---- 열기 ----
    def _open(self, m: OpenIn) -> ToolOutcome:
        chunk = self._get(m.paragraph_id)
        logged = {"paragraph_id": m.paragraph_id}
        if chunk is None:
            return _error(
                f"{m.paragraph_id}는 {self.label}의 조각도 검색 결과에 나온 조각도 아니다. "
                "검색 결과의 chunk_id를 그대로 적어 다시 연다",
                **logged,
            )
        if m.paragraph_id not in self.opened:
            self.opened.append(m.paragraph_id)
        prev_id, next_id = self._neighbors(chunk)
        body = {
            "chunk_id": chunk.chunk_id,
            "location": chunk.location.label,
            "text": chunk.text,
            "prev": prev_id,
            "next": next_id,
        }
        return ToolOutcome(_json(body), result_ids=[chunk.chunk_id], logged_input=logged)

    # ---- 제출 ----
    def _check_ids(self, ids: list[str]) -> str | None:
        """없는 ID·받는 범위 밖·안 연 문단이면 고칠 방법 한 줄, 통과면 None."""
        if not SUBMIT_MIN <= len(ids) <= SUBMIT_MAX:
            return (
                f"문단은 {SUBMIT_MIN}~{SUBMIT_MAX}개를 낸다 (받은 수 {len(ids)}). "
                "연 문단에서 골라 다시 낸다"
            )
        for pid in ids:
            if self._get(pid) is None:
                return (
                    f"{pid}는 {self.label}의 조각도 검색 결과에 나온 조각도 아니다. "
                    "검색 결과의 chunk_id를 그대로 적는다"
                )
            if pid not in self.opened:
                return f"{pid}는 열지 않은 문단이다. open_paragraph로 먼저 연다"
        return None

    def _submit_compare(self, m: SubmitCompareIn) -> ToolOutcome:
        logged = {"paragraph_ids": list(m.paragraph_ids)}
        if bad := self._check_ids(m.paragraph_ids):
            return _error(bad, **logged)
        if not m.why.strip():
            return _error("why가 비었다. 구성요소와 문단의 대응을 한두 문장으로 적는다", **logged)
        done = Submitted(paragraph_ids=list(m.paragraph_ids), why=m.why)
        return ToolOutcome("받음", done=done, result_ids=list(m.paragraph_ids), logged_input=logged)

    def _submit_agent(self, m: SubmitAgentIn) -> ToolOutcome:
        ids = [it.paragraph_id for it in m.items]
        logged = {"paragraph_ids": ids, "judgment": m.judgment.value}
        if bad := self._check_ids(ids):
            return _error(bad, **logged)
        if not m.why.strip():
            return _error("why가 비었다. 판정 이유를 한두 문장으로 적는다", **logged)
        for it in m.items:
            chunk = self._get(it.paragraph_id)
            assert chunk is not None  # _check_ids가 걸렀다
            if not it.quote.strip() or _squash(it.quote) not in _squash(chunk.text):
                return _error(
                    f"{it.paragraph_id}의 quote가 문단 글에 그대로 없다. "
                    "연 문단에서 한 글자도 바꾸지 않고 옮겨 다시 낸다",
                    **logged,
                )
        done = Submitted(
            paragraph_ids=ids,
            why=m.why,
            items=[SubmittedItem(it.paragraph_id, it.quote) for it in m.items],
            judgment=m.judgment,
        )
        return ToolOutcome("받음", done=done, result_ids=ids, logged_input=logged)

    # ---- 포기 ----
    def _give_up(self, m: GiveUpIn) -> ToolOutcome:
        logged = {"reason": m.reason}
        if len(m.tried) > TRIED_MAX:
            return _error(f"tried는 {TRIED_MAX}자 이하로 줄여 다시 부른다", **logged)
        return ToolOutcome("끝", done=GiveUp(reason=m.reason, tried=m.tried), logged_input=logged)

    # ---- 도구 표 ----
    def _description(self, name: str) -> str:
        path = self.root / "prompts" / "recheck" / "tools" / f"{name}.md"
        return path.read_text(encoding="utf-8").strip()

    def specs(self, judge: Literal["compare", "agent"]) -> list[ToolSpec]:
        submit = (
            ToolSpec(
                "submit_evidence",
                self._description("submit_evidence"),
                SubmitCompareIn,
                self._submit_compare,
                terminal=True,
            )
            if judge == "compare"
            else ToolSpec(
                "submit_evidence",
                self._description("submit_evidence_judge"),
                SubmitAgentIn,
                self._submit_agent,
                terminal=True,
            )
        )
        return [
            ToolSpec(
                "search_bm25",
                self._description("search_bm25"),
                SearchIn,
                lambda m: self._search("bm25", m),
            ),
            ToolSpec(
                "search_vector",
                self._description("search_vector"),
                SearchIn,
                lambda m: self._search("vector", m),
            ),
            ToolSpec("open_paragraph", self._description("open_paragraph"), OpenIn, self._open),
            submit,
            ToolSpec(
                "give_up",
                self._description("give_up"),
                GiveUpIn,
                self._give_up,
                terminal=True,
            ),
        ]
