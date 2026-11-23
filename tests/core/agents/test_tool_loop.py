"""task-1: 공통 도구 루프. 가짜 전송층만, 네트워크·API 키 없음."""

import json

import pytest
from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.agents.tool_loop import (
    GiveUp,
    LoopLimits,
    RecheckToolFailed,
    ToolOutcome,
    ToolSpec,
    run_tool_loop,
)
from patent_ai.core.llm.errors import ModelCallFailed
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import ConverseResponse, FakeTransport

STEP = "t.s"


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    k: int


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraph_id: str


class SubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    why: str


class GiveUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


def use(name, input_, id_="tu_1"):
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


def reply(*blocks):
    return ConverseResponse(list(blocks), 100, 10, "tool_use")


def text_reply(text):
    return ConverseResponse([{"type": "text", "text": text}], 100, 10, "end_turn")


def make_tools(ran: list):
    def search(m):
        ran.append(("search", m.query))
        return ToolOutcome("결과", result_ids=["D1-1", "D1-2"], logged_input={"query": m.query})

    def open_(m):
        ran.append(("open", m.paragraph_id))
        return ToolOutcome("글", logged_input={"paragraph_id": m.paragraph_id})

    def submit(m):
        ran.append(("submit", m.why))
        return ToolOutcome("받음", done={"why": m.why})

    def give_up(m):
        return ToolOutcome("끝", done=GiveUp(reason=m.reason))

    return [
        ToolSpec("search", "검색", SearchIn, search),
        ToolSpec("open_paragraph", "열기", OpenIn, open_),
        ToolSpec("submit", "제출", SubmitIn, submit, terminal=True),
        ToolSpec("give_up", "포기", GiveUpIn, give_up, terminal=True),
    ]


@pytest.fixture
def env(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "s:\n  model: fake-model-1\n  effort: medium\n  max_tokens: 256\n  prompt: prompts/p.md\n",
        encoding="utf-8",
    )
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.md").write_text("도구로 찾는다", encoding="utf-8")
    return tmp_path


def run(env, items, limits=None, ran=None, tools=None):
    t = FakeTransport({STEP: list(items)})
    ctx = RunContext("run-1", CallBudget(), MemoryRecorder(), t, None)
    ran = [] if ran is None else ran
    result = run_tool_loop(
        STEP,
        {},
        "시작",
        tools or make_tools(ran),
        ctx=ctx,
        limits=limits or LoopLimits(tool_calls=8, turns=10),
        config_dir=env,
        root=env,
    )
    return result, t, ran


def test_평소_검색_열기_제출_세_차례(env):
    r, t, ran = run(
        env,
        [
            reply(use("search", {"query": "제어부", "k": 5})),
            reply(use("open_paragraph", {"paragraph_id": "D1-1"})),
            reply(use("submit", {"why": "대응"})),
        ],
    )
    assert r.outcome == "submitted" and r.value == {"why": "대응"}
    assert (r.turns, r.tool_calls) == (3, 3)
    assert [s.tool_name for s in r.steps] == ["search", "open_paragraph", "submit"]
    assert r.steps[0].result_ids == ["D1-1", "D1-2"] and r.steps[0].turn == 1
    assert r.queries == ["제어부"]
    assert ran == [("search", "제어부"), ("open", "D1-1"), ("submit", "대응")]
    # 둘째 차례 messages: 시작, 첫 답 블록 그대로, tool_result
    m = t.calls[1]["messages"]
    assert m[0] == {"role": "user", "content": "시작"}
    assert m[1]["role"] == "assistant" and m[1]["content"][0]["id"] == "tu_1"
    assert m[2]["content"][0]["type"] == "tool_result"
    assert m[2]["content"][0]["tool_use_id"] == "tu_1"


def test_바로_give_up이면_gave_up(env):
    r, _, _ = run(env, [reply(use("give_up", {"reason": "other"}))])
    assert r.outcome == "gave_up" and r.value == GiveUp(reason="other")
    assert r.tool_calls == 1


def test_없는_도구_이름은_오류_결과_뒤_다시_고른다(env):
    r, t, _ = run(
        env,
        [reply(use("browse", {})), reply(use("submit", {"why": "x"}))],
    )
    assert r.outcome == "submitted"
    res = t.calls[1]["messages"][2]["content"][0]
    assert res["is_error"] is True
    assert "없는 도구 browse" in res["content"] and "search" in res["content"]
    assert r.steps[0].is_error is True


def test_스키마_밖_인자는_오류_결과이고_받은_글자는_안_넣는다(env):
    r, t, ran = run(
        env,
        [
            reply(use("search", {"query": "비밀글자", "k": "ZZZ", "extra": 1})),
            reply(use("submit", {"why": "x"})),
        ],
    )
    res = t.calls[1]["messages"][2]["content"][0]
    assert res["is_error"] is True
    assert "k" in res["content"] and "extra" in res["content"]
    assert "비밀글자" not in res["content"] and "ZZZ" not in res["content"]
    assert ran == [("submit", "x")]  # 검색은 안 돌았다
    assert r.queries == []


def test_글만_답하면_안내_메시지_뒤_계속(env):
    r, t, _ = run(env, [text_reply("끝났습니다"), reply(use("submit", {"why": "x"}))])
    assert r.outcome == "submitted" and r.turns == 2 and r.tool_calls == 1
    last = t.calls[1]["messages"][-1]
    assert last["role"] == "user" and "도구로만 답한다" in json.dumps(last, ensure_ascii=False)


def test_도구_호출_상한이면_limit_reached이고_마지막_도구는_안_돈다(env):
    items = [reply(use("search", {"query": f"q{i}", "k": 1}, f"tu_{i}")) for i in range(3)]
    r, _, ran = run(env, items, limits=LoopLimits(tool_calls=2, turns=10))
    assert r.outcome == "limit_reached" and r.tool_calls == 2
    assert ran == [("search", "q0"), ("search", "q1")]
    assert r.queries == ["q0", "q1"]


def test_도구_호출_상한에_닿으면_모델을_한_번_더_부르지_않는다(env):
    items = [reply(use("search", {"query": f"q{i}", "k": 1}, f"tu_{i}")) for i in range(3)]
    r, t, _ = run(env, items, limits=LoopLimits(tool_calls=2, turns=10))
    assert r.outcome == "limit_reached" and r.turns == 2
    assert len(t.calls) == 2


def test_차례_상한이면_limit_reached(env):
    items = [reply(use("search", {"query": f"q{i}", "k": 1}, f"tu_{i}")) for i in range(5)]
    r, t, _ = run(env, items, limits=LoopLimits(tool_calls=8, turns=2))
    assert r.outcome == "limit_reached" and r.turns == 2
    assert len(t.calls) == 2


def test_모델_호출_실패는_model_call_failed(env):
    r, _, _ = run(env, [ModelCallFailed("끊김")])
    assert r.outcome == "model_call_failed" and r.steps == []


def test_실행_호출_상한은_limit_reached(env):
    # 단계 설정의 실행 합계 상한(max_model_calls)이 1이면 둘째 차례에서 상한 예외
    with (env / "t.yaml").open("a", encoding="utf-8") as f:
        f.write("  max_model_calls: 1\n")
    items = [reply(use("search", {"query": "a", "k": 1})), reply(use("submit", {"why": "x"}))]
    r, _, _ = run(env, items)
    assert r.outcome == "limit_reached" and r.turns == 2


def test_도구가_RecheckToolFailed를_던지면_tool_failed(env):
    def boom(m):
        raise RecheckToolFailed("검색 실패")

    tools = [ToolSpec("search", "검색", SearchIn, boom)]
    r, _, _ = run(env, [reply(use("search", {"query": "a", "k": 1}))], tools=tools)
    assert r.outcome == "tool_failed"


def test_RecheckToolFailed_단계_기록에_실패한_호출의_질의와_k가_남는다(env):
    def boom(m):
        raise RecheckToolFailed("검색 실패")

    tools = [ToolSpec("search", "검색", SearchIn, boom)]
    r, _, _ = run(env, [reply(use("search", {"query": "수조", "k": 3}))], tools=tools)
    assert r.steps[-1].logged_input == {"query": "수조", "k": 3}
    assert r.steps[-1].is_error


def test_프로그래밍_오류는_잡지_않는다(env):
    def bug(m):
        raise KeyError("버그")

    tools = [ToolSpec("search", "검색", SearchIn, bug)]
    with pytest.raises(KeyError):
        run(env, [reply(use("search", {"query": "a", "k": 1}))], tools=tools)


def test_한_차례_tool_use_둘이면_tool_result_둘이_user_메시지_하나(env):
    r, t, _ = run(
        env,
        [
            reply(
                use("search", {"query": "a", "k": 1}, "tu_a"),
                use("open_paragraph", {"paragraph_id": "D1-1"}, "tu_b"),
            ),
            reply(use("submit", {"why": "x"}, "tu_c")),
        ],
    )
    msgs = t.calls[1]["messages"]
    assert len(msgs) == 3
    ids = [b["tool_use_id"] for b in msgs[2]["content"]]
    assert ids == ["tu_a", "tu_b"]
    assert r.tool_calls == 3


def test_같은_질의는_queries에_한_번만(env):
    items = [
        reply(use("search", {"query": "a", "k": 1}, "t1")),
        reply(use("search", {"query": "a", "k": 2}, "t2")),
        reply(use("submit", {"why": "x"}, "t3")),
    ]
    r, _, _ = run(env, items)
    assert r.queries == ["a"]


def test_API_도구_정의는_strict이고_모든_칸이_required():
    class Defaulted(BaseModel):
        model_config = ConfigDict(extra="forbid")
        query: str = ""
        k: int = 5

    spec = ToolSpec("search", "검색 설명", Defaulted, lambda m: ToolOutcome("x"))
    d = spec.api_definition()
    assert d["name"] == "search" and d["description"] == "검색 설명" and d["strict"] is True
    s = d["input_schema"]
    assert s["additionalProperties"] is False
    assert set(s["required"]) == {"query", "k"}


def test_길이_범위_개수_제약_키는_정의에_싣지_않는다():
    class Item(BaseModel):
        model_config = ConfigDict(extra="forbid")
        text: str = Field(min_length=1, max_length=50, pattern="^a")

    class M(BaseModel):
        model_config = ConfigDict(extra="forbid")
        q: str = Field(max_length=200)
        k: int = Field(ge=1, le=10)
        ids: list[str] = Field(min_length=1, max_length=5)
        items: list[Item]

    s = ToolSpec("x", "d", M, lambda m: ToolOutcome("x")).api_definition()["input_schema"]
    dumped = json.dumps(s)
    for key in ("maxLength", "minLength", "minimum", "maximum", "maxItems", "minItems", "pattern"):
        assert key not in dumped
    # 중첩 모델도 additionalProperties false + required 전부
    item_schema = s["$defs"]["Item"]
    assert item_schema["additionalProperties"] is False and item_schema["required"] == ["text"]
