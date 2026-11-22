"""근거 다시 찾기 에이전트 한 번: 구성요소 하나 × 인용문헌 하나 (recheck design 3·4절).

모델이 도구(검색·열기·제출·포기)를 골라 부르는 대화를 `run_tool_loop`로 돈다.
이 모듈은 대화를 시작하고 (시스템 프롬프트 변수·도구 표를 만든다)
끝 결과를 돌려줄 뿐, 끝 상태를 대비 줄로 바꾸는 일은 `recheck/run.py`가 한다.
검색은 부르는 쪽이 넘긴 검색기 객체 하나만 쓴다 (1차·다시 찾기가 같은 객체).
"""

from dataclasses import dataclass
from pathlib import Path

from patent_ai.core.agents.tool_loop import LoopLimits, LoopResult, run_tool_loop
from patent_ai.core.f3_claim_compare.citations import ResolvedCitation
from patent_ai.core.f3_claim_compare.elements import ClaimElement
from patent_ai.core.f3_claim_compare.inputs import F3Settings
from patent_ai.core.f3_claim_compare.recheck.config import RecheckSettings
from patent_ai.core.f3_claim_compare.recheck.tools import CiteToolbox
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.limits import RunContext
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository

STEP = "recheck.agent"
# 대화의 첫 user 메시지 (시스템 프롬프트에 할 일이 다 있어 짧게 시작만 알린다)
FIRST_USER = "위 구성요소에 대응하는 문단을 이 인용문헌 안에서 찾고, 도구로 답하세요."
JUDGE_NOTE_FILE = "prompts/recheck/judge_note_agent.md"


@dataclass
class AgentRun:
    loop: LoopResult
    toolbox: CiteToolbox  # 이 대화의 검색 결과·연 문단 (끝 값의 조각을 찾을 때 쓴다)


def _judge_note(judge: str, root: Path) -> str:
    """판정까지 에이전트가 맡을 때만 시스템 프롬프트에 붙는 안내 (compare면 빈 글)."""
    if judge != "agent":
        return ""
    return (root / JUDGE_NOTE_FILE).read_text(encoding="utf-8").strip()


def run_cite_agent(
    *,
    element: ClaimElement,
    claim_text: str,
    cite: ResolvedCitation,
    shown: set[str],
    settings: F3Settings,
    recheck: RecheckSettings,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
    root: Path | None = None,
    config_dir: Path | None = None,
) -> AgentRun:
    """구성요소 하나를 인용문헌 하나 안에서 다시 찾는 대화를 돈다.

    shown = 1차에 모델에 보여 준 조각 ID (도구가 결과에 "(1차에 이미 봄)"으로 표시만 한다).
    모델 호출 예외는 루프 안에서 끝말(limit_reached·model_call_failed)로 바뀌어 돌아온다.
    """
    assert cite.doc_id is not None  # 본문 없는 인용문헌은 부르는 쪽이 이미 보류한다
    root = root or REPO_ROOT
    toolbox = CiteToolbox(
        searcher,
        repo,
        settings.search.index_version,
        cite.doc_id,
        cite.label,
        set(shown),
        recheck.search.k_max,
        recheck.search.snippet_chars,
        root=root,
    )
    variables = {
        "citation": cite.label,
        "chunk_count": str(cite.chunk_count),
        "tool_limit": str(recheck.limits.tool_calls),
        "judge_note": _judge_note(recheck.recheck_judge, root),
        "claim_text": claim_text,
        "element": element.text,
    }
    loop = run_tool_loop(
        STEP,
        variables,
        FIRST_USER,
        toolbox.specs(recheck.recheck_judge),
        ctx=ctx,
        limits=LoopLimits(tool_calls=recheck.limits.tool_calls, turns=recheck.limits.turns),
        config_dir=config_dir,
        root=root,
    )
    return AgentRun(loop, toolbox)
