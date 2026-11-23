"""모델 답에서 JSON 읽기: 내용이 빠지지 않는 겉모양만 벗긴다 (네트워크·API 키 없음)."""

import json

import pytest
from pydantic import BaseModel, ConfigDict

from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.json_answer import parse_answer
from patent_ai.core.llm.limits import CallBudget
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from tests.core.llm.test_client import FIX, VARS

OBJ = {"title": "가 ]} ``` 나", "rows": [{"n": 1}]}
TEXT = json.dumps(OBJ, ensure_ascii=False)


@pytest.mark.parametrize(
    "text",
    [
        f"```json\n{TEXT}\n```",
        f"```\n{TEXT}\n```\n",
        f"  \n{TEXT}\n",
        # F1에서 실제로 온 꼬리 모양 (A 실험)
        f"{TEXT}]}}",
        f'{TEXT}], "claim_rows_placeholder": null}}',
        f"```json\n{TEXT}]}}\n```",
    ],
)
def test_코드_블록과_내용_없는_꼬리는_벗겨서_읽는다(text):
    assert parse_answer(text, truncated=False) == OBJ


@pytest.mark.parametrize(
    "text",
    [
        "",
        "그냥 글",
        f"설명입니다.\n{TEXT}",
        f"{TEXT}\n이상입니다.",
        # 꼬리에 값이 있으면 버리지 않고 실패로 둔다 (내용이 조용히 빠지지 않게)
        f'{TEXT}], "claim_rows": [{{"n": 2}}]}}',
        f'{TEXT}, "score": 3}}',
        f"{TEXT}\n{TEXT}",
        # 닫히지 않은 JSON은 고쳐 쓰지 않는다
        TEXT[:-1],
        f"```json\n{TEXT[:-1]}\n```",
        "[1, 2]]",
    ],
)
def test_내용이_빠질_수_있는_답은_읽지_않는다(text):
    with pytest.raises(json.JSONDecodeError):
        parse_answer(text, truncated=False)


def test_잘린_답은_꼬리를_벗기지_않는다():
    with pytest.raises(json.JSONDecodeError):
        parse_answer(f"{TEXT}]}}", truncated=True)


class Shaped(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


def _call(text, stop_reason="end_turn"):
    fake = FakeTransport({"test.summarize": TransportResponse(text, 10, 5, stop_reason)})
    return call_model(
        "test.summarize",
        VARS,
        Shaped,
        "run-1",
        transport=fake,
        config_dir=FIX / "config",
        root=FIX,
        budget=CallBudget(),
    )


def test_call_model은_꼬리_붙은_답을_통과시키고_경고를_남긴다(caplog):
    assert _call('{"title": "비밀 글"}]}').parsed.title == "비밀 글"
    assert "JSON 밖 글자를 벗기고 읽음" in caplog.text
    assert "비밀 글" not in caplog.text  # 답 글자는 로그에 안 남긴다


def test_call_model은_max_tokens로_잘린_답의_꼬리를_벗기지_않는다():
    with pytest.raises(ModelOutputInvalid) as e:
        _call('{"title": "가"}]}', stop_reason="max_tokens")
    assert (e.value.stop_reason, e.value.invalid_kind) == ("max_tokens", "not_json:broken")


def test_벗긴_뒤에도_스키마_검사는_그대로다():
    with pytest.raises(ModelOutputInvalid) as e:
        _call('```json\n{"title": "가", "몰래": 1}\n```')
    assert e.value.invalid_kind == "unknown_key"
