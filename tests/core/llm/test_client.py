"""task-1: 호출 인터페이스와 설정·프롬프트 읽기 (가짜 전송층만, 네트워크·API 키 없음)."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelConfigError, ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget
from patent_ai.core.llm.transport import (
    AnthropicTransport,
    FakeTransport,
    TransportResponse,
    parse_anthropic_message,
)

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
VARS = {"lines": 2, "text": "청구항 1은 진보성이 없다"}


class Summary(BaseModel):
    title: str
    score: int


def run(transport, step="test.summarize", variables=VARS, schema=None):
    return call_model(
        step,
        variables,
        schema,
        "run-1",
        transport=transport,
        config_dir=FIX / "config",
        root=FIX,
        budget=CallBudget(),
    )


def test_평소_스키마_없이_텍스트와_설정값을_돌려준다():
    fake = FakeTransport({"test.summarize": TransportResponse("요약입니다", 1000, 500)})
    r = run(fake)
    assert r.text == "요약입니다"
    assert r.parsed is None
    assert r.model == "fake-model-1"
    assert (r.input_tokens, r.output_tokens) == (1000, 500)
    assert r.from_cache is False
    assert r.elapsed_ms >= 0
    # 1000*3/1e6 + 500*15/1e6
    assert r.cost == pytest.approx(0.0105)


def test_모델과_설정값은_설정_파일에서_전송층으로_간다():
    fake = FakeTransport({"test.summarize": TransportResponse("x", 1, 1)})
    run(fake)
    call = fake.calls[0]
    assert call["model"] == "fake-model-1"
    assert call["effort"] == "medium"
    assert call["max_tokens"] == 256


def test_프롬프트_파일의_변수가_채워진다():
    fake = FakeTransport({"test.summarize": TransportResponse("x", 1, 1)})
    run(fake)
    assert (
        fake.calls[0]["prompt"]
        == "다음 거절이유를 2 줄로 요약하세요.\n본문: 청구항 1은 진보성이 없다\n"
    )


def test_스키마가_있으면_JSON을_읽어_parsed에_객체를_준다():
    fake = FakeTransport(
        {"test.summarize": TransportResponse('{"title": "진보성", "score": 3}', 1, 1)}
    )
    r = run(fake, schema=Summary)
    assert r.parsed == Summary(title="진보성", score=3)


def test_가격이_없으면_cost는_None():
    fake = FakeTransport({"test.nocost": TransportResponse("x", 10, 10)})
    assert run(fake, step="test.nocost").cost is None


def test_설정에_단계가_없으면_ModelConfigError():
    with pytest.raises(ModelConfigError, match="nope"):
        run(FakeTransport({}), step="test.nope")


def test_설정_파일이_없으면_ModelConfigError():
    with pytest.raises(ModelConfigError, match="nofile"):
        run(FakeTransport({}), step="nofile.summarize")


def test_step_모양이_틀리면_ModelConfigError():
    with pytest.raises(ModelConfigError):
        run(FakeTransport({}), step="summarize")


def test_프롬프트_파일이_없으면_ModelConfigError():
    with pytest.raises(ModelConfigError, match="does_not_exist"):
        run(FakeTransport({}), step="test.missingprompt")


def test_프롬프트_변수가_빠지면_이름을_담은_오류():
    with pytest.raises(ModelConfigError, match="text"):
        run(FakeTransport({}), variables={"lines": 2})


def test_출력이_JSON이_아니면_ModelOutputInvalid():
    fake = FakeTransport({"test.summarize": TransportResponse("그냥 글", 1, 1)})
    with pytest.raises(ModelOutputInvalid, match="JSON"):
        run(fake, schema=Summary)


def test_출력이_스키마에_안_맞으면_ModelOutputInvalid에_이유():
    fake = FakeTransport({"test.summarize": TransportResponse('{"title": "x"}', 1, 1)})
    with pytest.raises(ModelOutputInvalid, match="score"):
        run(fake, schema=Summary)


def test_attempt_기본값은_1이고_바꿀_수_있다():
    fake = FakeTransport({"test.summarize": TransportResponse("x", 1, 1)})
    r = call_model(
        "test.summarize",
        VARS,
        None,
        "run-1",
        attempt=2,
        transport=fake,
        config_dir=FIX / "config",
        root=FIX,
        budget=CallBudget(),
    )
    assert r.text == "x"


def test_SDK_응답_모양을_파싱한다():
    class Block:
        def __init__(self, type, text=""):
            self.type, self.text = type, text

    class Usage:
        input_tokens = 12
        output_tokens = 7

    class Msg:
        content = [Block("text", "안녕"), Block("tool_use"), Block("text", "하세요")]
        usage = Usage()

    resp = parse_anthropic_message(Msg())
    assert resp == TransportResponse("안녕하세요", 12, 7)
    assert AnthropicTransport is not None  # 만들거나 부르지는 않는다
