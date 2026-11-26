"""의견서가 보정 결과와 F1 항별 심사관 근거를 받는 순서 (설정 opinion_after_amendment).

기대값은 docs/features/F4/tasks.md `m3-i2-opinion-amend`에서 가져왔다:
켜면 방향 → 보정 → 의견서(f4.opinion_amended) 순서이고, 의견서 프롬프트에
그 묶음의 보정 글자와 항별 심사관 위치가 들어간다. 끄면 지금 순서(f4.opinion) 그대로.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.config import load_f4_options
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
OK = {"value": "confirmed", "checked": "원문 대조"}


def _case() -> dict:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    # F1 항별 줄: 심사관이 제2항에 D1 [0021]을 들었다 (fixture에는 줄이 없어 여기서 더한다)
    data["oa"]["claim_rows"] = [
        {
            "claim": 2,
            "rejection": 1,
            "citations": ["D1"],
            "locations": {"D1": ["[0021]"]},
            "raw_text": "제2항의 김 서림 방지 막은 인용발명 1의 식별번호 [0021]에 개시",
            "page": 2,
            "status": OK,
        }
    ]
    return data


def _answer(name: str) -> TransportResponse:
    text = (FIXTURES / "llm" / f"{name}.json").read_text("utf-8")
    return TransportResponse(text, 100, 50)


def _run(after: bool) -> FakeTransport:
    transport = FakeTransport(
        {
            "f4.direction": [_answer("direction_inventive"), _answer("direction_clarity")],
            "f4.opinion": [_answer("opinion_inventive"), _answer("opinion_clarity")],
            "f4.opinion_amended": [_answer("opinion_inventive"), _answer("opinion_clarity")],
            "f4.amendment": [_answer("amendment_inventive"), _answer("amendment_clarity")],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    options = dataclasses.replace(load_f4_options(), opinion_after_amendment=after)
    run_f4(F4Input.model_validate(_case()), ctx=ctx, options=options)
    return transport


def test_기본값은_꺼져_있다():
    assert load_f4_options().opinion_after_amendment is False


def test_스위치가_bool이_아니면_멈춘다(tmp_path):
    src = (Path(__file__).resolve().parents[3] / "config" / "f4.yaml").read_text("utf-8")
    (tmp_path / "f4.yaml").write_text(
        src.replace("opinion_after_amendment: false", 'opinion_after_amendment: "yes"'), "utf-8"
    )
    with pytest.raises(ModelConfigError):
        load_f4_options(tmp_path)


def test_끄면_지금_순서와_단계_그대로():
    steps = [c["step"] for c in _run(after=False).calls]
    assert "f4.opinion_amended" not in steps
    assert steps.index("f4.opinion") < steps.index("f4.amendment")


def test_켜면_보정_뒤에_의견서를_부른다():
    steps = [c["step"] for c in _run(after=True).calls]
    assert "f4.opinion" not in steps
    assert steps.index("f4.amendment") < steps.index("f4.opinion_amended")


def test_켜면_의견서_프롬프트에_보정_글자와_항별_심사관_위치가_들어간다():
    calls = [c for c in _run(after=True).calls if c["step"] == "f4.opinion_amended"]
    inventive = calls[0]["prompt"]
    # 보정 초안 답(amendment_inventive)의 제1항 보정 글자
    assert "투명 덮개를 포함하고, 상기 덮개에 김 서림 방지 막을" in inventive
    # F1 항별 줄의 심사관 위치
    assert "[0021]" in inventive
    assert "제2항의 김 서림 방지 막은" in inventive
