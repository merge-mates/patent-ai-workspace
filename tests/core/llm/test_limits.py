"""task-3: 호출 상한·전송 오류 재시도·호출 기록 (가짜 전송층만, 네트워크·API 키 없음)."""

import logging
from pathlib import Path

import pytest

from patent_ai.core.llm.cache import MemoryCache
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder
from patent_ai.core.llm.transport import TransportError, TransportResponse

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
VARS = {"lines": 2, "text": "청구항 1은 진보성이 없다"}
OK = TransportResponse("답", 600, 100)


class ScriptedTransport:
    """답이나 예외를 차례로 낸다. 다 쓰면 마지막 것을 계속 낸다."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def complete(self, **kwargs):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def make_config(tmp_path, **limits):
    """설정 파일을 임시 폴더에 만든다 (limits 칸을 단계 설정에 붙임)."""
    extra = "".join(f"  {k}: {v}\n" for k, v in limits.items())
    (tmp_path / "t.yaml").write_text(
        "s:\n  model: fake-model-1\n  temperature: 0.0\n  max_tokens: 256\n"
        "  prompt: prompts/summarize.txt\n"
        "  price_per_mtok_input: 3.0\n  price_per_mtok_output: 15.0\n" + extra,
        encoding="utf-8",
    )
    return tmp_path


def run(transport, cfg, budget, recorder, run_id="run-1", cache=None, variables=VARS, sleeps=None):
    return call_model(
        "t.s",
        variables,
        None,
        run_id,
        transport=transport,
        cache=cache,
        config_dir=cfg,
        root=FIX,
        budget=budget,
        recorder=recorder,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def test_평소_상한_안이면_성공하고_기록이_한_줄_남는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=3)
    rec = MemoryRecorder()
    run(ScriptedTransport(OK), cfg, CallBudget(), rec)
    assert len(rec.records) == 1
    r = rec.records[0]
    assert (r.run_id, r.step, r.model) == ("run-1", "t.s", "fake-model-1")
    assert (r.input_tokens, r.output_tokens) == (600, 100)
    assert r.cost == pytest.approx(600 * 3 / 1e6 + 100 * 15 / 1e6)
    assert r.elapsed_ms >= 0
    assert (r.from_cache, r.attempt, r.outcome) == (False, 1, "ok")


def test_경계_딱_상한만큼은_성공한다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=2)
    budget, rec, t = CallBudget(), MemoryRecorder(), ScriptedTransport(OK)
    run(t, cfg, budget, rec)
    run(t, cfg, budget, rec)
    assert t.calls == 2
    assert [r.outcome for r in rec.records] == ["ok", "ok"]


def test_상한_더하기_하나는_예외이고_전송층을_부르지_않는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=2)
    budget, rec, t = CallBudget(), MemoryRecorder(), ScriptedTransport(OK)
    run(t, cfg, budget, rec)
    run(t, cfg, budget, rec)
    with pytest.raises(ModelCallLimitExceeded) as e:
        run(t, cfg, budget, rec)
    assert e.value.limit == "max_model_calls"
    assert e.value.used == 2
    assert e.value.limit_value == 2
    assert t.calls == 2  # 세 번째는 전송층까지 가지 않음
    assert rec.records[-1].outcome == "limit_exceeded"


def test_다른_run_id는_따로_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    budget, rec, t = CallBudget(), MemoryRecorder(), ScriptedTransport(OK)
    run(t, cfg, budget, rec, run_id="a")
    run(t, cfg, budget, rec, run_id="b")
    with pytest.raises(ModelCallLimitExceeded):
        run(t, cfg, budget, rec, run_id="a")


def test_입력_토큰_상한은_쓴_양이_상한에_닿으면_다음_호출을_막는다(tmp_path):
    cfg = make_config(tmp_path, max_input_tokens=1000)
    budget, rec, t = CallBudget(), MemoryRecorder(), ScriptedTransport(OK)  # 호출당 600
    run(t, cfg, budget, rec)  # 쓴 양 0 -> 600
    run(t, cfg, budget, rec)  # 600 < 1000 -> 1200
    with pytest.raises(ModelCallLimitExceeded) as e:
        run(t, cfg, budget, rec)
    assert e.value.limit == "max_input_tokens"
    assert e.value.used == 1200
    assert t.calls == 2


def test_캐시_적중은_상한에_세지_않고_기록은_남는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    budget, rec, t = CallBudget(), MemoryRecorder(), ScriptedTransport(OK)
    cache = MemoryCache()
    run(t, cfg, budget, rec, cache=cache)
    run(t, cfg, budget, rec, cache=cache)
    run(t, cfg, budget, rec, cache=cache)
    assert t.calls == 1
    assert [(r.from_cache, r.outcome) for r in rec.records] == [
        (False, "ok"),
        (True, "cache_hit"),
        (True, "cache_hit"),
    ]
    assert rec.records[1].cost == 0.0


def test_상한이_설정에_없으면_막지_않고_경고를_한_번만_남긴다(tmp_path, caplog):
    cfg = make_config(tmp_path)
    budget, rec, t = CallBudget(), MemoryRecorder(), ScriptedTransport(OK)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            run(t, cfg, budget, rec)
    assert t.calls == 5
    warns = [m for m in caplog.messages if "상한" in m]
    assert len(warns) == 1


def test_429가_계속되면_max_retries_뒤_ModelCallFailed(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    rec, sleeps = MemoryRecorder(), []
    t = ScriptedTransport(TransportError("429 너무 많은 요청", retryable=True))
    with pytest.raises(ModelCallFailed) as e:
        run(t, cfg, CallBudget(), rec, sleeps=sleeps)
    assert "429" in str(e.value)
    assert t.calls == 3  # 처음 1 + 다시 2
    assert len(sleeps) == 2  # 다시 부르기 전에만 쉰다
    assert [r.outcome for r in rec.records] == ["transport_error"] * 3


def test_429_뒤_성공하면_결과를_돌려준다(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    rec = MemoryRecorder()
    t = ScriptedTransport(TransportError("429", retryable=True), OK)
    r = run(t, cfg, CallBudget(), rec)
    assert r.text == "답"
    assert [x.outcome for x in rec.records] == ["transport_error", "ok"]


def test_max_retries가_없으면_다시_부르지_않는다(tmp_path):
    cfg = make_config(tmp_path)
    t = ScriptedTransport(TransportError("연결 끊김", retryable=True))
    with pytest.raises(ModelCallFailed):
        run(t, cfg, CallBudget(), MemoryRecorder())
    assert t.calls == 1


def test_다시_불러도_소용없는_오류는_바로_실패한다(tmp_path):
    cfg = make_config(tmp_path, max_retries=3)
    t = ScriptedTransport(TransportError("400 잘못된 요청", retryable=False))
    with pytest.raises(ModelCallFailed):
        run(t, cfg, CallBudget(), MemoryRecorder())
    assert t.calls == 1


def test_다시_부르는_것도_호출_수에_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=2, max_retries=5)
    t = ScriptedTransport(TransportError("429", retryable=True))
    with pytest.raises(ModelCallLimitExceeded) as e:
        run(t, cfg, CallBudget(), MemoryRecorder())
    assert e.value.used == 2
    assert t.calls == 2
