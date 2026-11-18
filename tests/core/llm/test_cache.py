"""task-2: 캐시와 녹화 응답 (가짜·녹화 전송층, 임시 폴더만. 네트워크·API 키 없음)."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import BaseModel

from patent_ai.core.llm.cache import FileCache, MemoryCache
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid, RecordingMissing
from patent_ai.core.llm.recorded import RecordedTransport, save_recording
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
VARS = {"lines": 2, "text": "청구항 1은 진보성이 없다"}
STEP = "test.summarize"


class Summary(BaseModel):
    title: str
    score: int


def run(transport, cache, variables=VARS, schema=None, attempt=1, root=FIX):
    return call_model(
        STEP,
        variables,
        schema,
        "run-1",
        attempt,
        transport=transport,
        cache=cache,
        config_dir=FIX / "config",
        root=root,
    )


def fake(text="요약입니다"):
    return FakeTransport({STEP: TransportResponse(text, 10, 5)})


@pytest.fixture(params=["memory", "file"])
def cache(request, tmp_path):
    return MemoryCache() if request.param == "memory" else FileCache(tmp_path / "cache")


def test_평소_두번째_호출은_캐시_전송층은_한번(cache):
    t = fake()
    first = run(t, cache)
    second = run(t, cache)
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.text == first.text
    assert (second.input_tokens, second.output_tokens) == (10, 5)
    assert len(t.calls) == 1


def test_캐시를_안_넘기면_매번_전송층으로_간다():
    t = fake()
    run(t, None)
    run(t, None)
    assert len(t.calls) == 2


def test_변수_하나가_바뀌면_캐시를_안_쓴다(cache):
    t = fake()
    run(t, cache)
    r = run(t, cache, variables={**VARS, "text": "청구항 1은 명확하지 않다"})
    assert r.from_cache is False
    assert len(t.calls) == 2


def test_프롬프트_파일_글자_하나가_바뀌면_캐시를_안_쓴다(cache, tmp_path):
    root = tmp_path / "root"
    shutil.copytree(FIX, root)
    t = fake()
    run(t, cache, root=root)
    prompt = root / "prompts" / "summarize.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "!", encoding="utf-8")
    r = run(t, cache, root=root)
    assert r.from_cache is False
    assert len(t.calls) == 2


def test_스키마_검사에_떨어진_답은_캐시에_안_쓰고_attempt2는_전송층으로_간다(tmp_path):
    cache = FileCache(tmp_path / "cache")
    t = fake("JSON 아님")
    with pytest.raises(ModelOutputInvalid):
        run(t, cache, schema=Summary)
    assert list((tmp_path / "cache").glob("*")) == []  # 캐시 0건
    # 같은 attempt=1 재호출도 캐시가 없으니 전송층으로 간다
    with pytest.raises(ModelOutputInvalid):
        run(t, cache, schema=Summary, attempt=1)
    # attempt=2 는 키가 다르다
    t.responses[STEP] = TransportResponse(json.dumps({"title": "a", "score": 1}), 1, 1)
    r = run(t, cache, schema=Summary, attempt=2)
    assert r.from_cache is False
    assert len(t.calls) == 3
    assert len(list((tmp_path / "cache").glob("*"))) == 1


def test_attempt가_다르면_성공한_답도_캐시를_안_쓴다(cache):
    t = fake()
    run(t, cache, attempt=1)
    r = run(t, cache, attempt=2)
    assert r.from_cache is False
    assert len(t.calls) == 2


def test_녹화_답을_읽는다(tmp_path):
    rec = tmp_path / "rec"
    live = fake("녹화된 답")
    # 가짜 전송층이 받은 호출 그대로 녹화 파일을 만든다
    run(live, None)
    c = live.calls[0]
    save_recording(
        rec,
        live.responses[STEP],
        step=STEP,
        model=c["model"],
        prompt=c["prompt"],
        temperature=c["temperature"],
        max_tokens=c["max_tokens"],
    )
    saved = next(rec.glob("*.json"))
    assert set(json.loads(saved.read_text(encoding="utf-8"))) == {
        "text",
        "input_tokens",
        "output_tokens",
        "model",
        "step",
    }
    r = run(RecordedTransport(rec), None)
    assert r.text == "녹화된 답"
    assert (r.input_tokens, r.output_tokens) == (10, 5)


def test_녹화가_없으면_RecordingMissing(tmp_path):
    with pytest.raises(RecordingMissing):
        run(RecordedTransport(tmp_path / "none"), None)


def test_녹화도_글자_하나가_다르면_못_찾는다(tmp_path):
    rec = tmp_path / "rec"
    live = fake()
    run(live, None)
    c = live.calls[0]
    save_recording(
        rec,
        live.responses[STEP],
        step=STEP,
        model=c["model"],
        prompt=c["prompt"],
        temperature=c["temperature"],
        max_tokens=c["max_tokens"],
    )
    with pytest.raises(RecordingMissing):
        run(RecordedTransport(rec), None, variables={**VARS, "text": "다른 본문"})
