"""최후거절이유통지 보정 제한 스위치(final_rejection_limit) 테스트. 진짜 모델 호출 없음.

기대값은 구현 계획 C7, `docs/features/F4/design.md`
4절(보정 제한)·7-2절(final_rejection_limit), product.md 5절 F4 6번에서 가져왔다.
코드는 제한 문구를 프롬프트에 넣고 표시만 한다. 보정이 제한 안인지 밖인지는 판정하지 않는다.
"""

import json
from pathlib import Path

from patent_ai.core.f4_response_draft.config import F4Options
from patent_ai.core.f4_response_draft.directions import NOTICE_FINAL_UNLIMITED, NOTICE_KIND_CHECK
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import FINAL_LIMIT_PROMPT, run_f4
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag
from patent_ai.core.schemas.direction import AmendmentLimit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
ON = F4Options(final_rejection_limit=True, max_units=20, max_candidates=3)
OFF = F4Options(final_rejection_limit=False, max_units=20, max_candidates=3)


def _limit_text() -> str:
    """프롬프트 파일의 제한 문구 (문구 자체는 테스트하지 않고, 들어갔는지만 본다)."""
    return (REPO_ROOT / FINAL_LIMIT_PROMPT).read_text("utf-8").strip()


def _case(notice_kind: str) -> F4Input:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    if notice_kind == "unknown":
        bad = {"value": "unverified", "reason": "not_extracted"}
        data["oa"]["notice_kind"] = {"value": "unknown", "status": bad}
        data["oa"]["status"] = bad
    elif notice_kind == "final":
        data["oa"]["notice_kind"] = {
            "value": "final",
            "raw_text": "최후거절이유통지",
            "page": 1,
            "status": {"value": "confirmed", "checked": "원문 대조"},
        }
    return F4Input.model_validate(data)


def _run(notice_kind: str, options: F4Options):
    def answers(*names):
        return [
            TransportResponse((FIXTURES / "llm" / f"{n}.json").read_text("utf-8"), 100, 50)
            for n in names
        ]

    transport = FakeTransport(
        {
            "f4.direction": answers("direction_inventive", "direction_clarity"),
            "f4.opinion": answers("opinion_inventive", "opinion_clarity"),
            "f4.amendment": answers("amendment_inventive", "amendment_clarity"),
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    out = run_f4(_case(notice_kind), ctx=ctx, options=options)
    prompts = [c["prompt"] for c in transport.calls if c["step"] == "f4.amendment"]
    assert len(prompts) == 2
    return out, prompts


def _checks(out) -> list[list[str]]:
    return [c.checks for d in out.directions for c in d.candidates]


def test_제한_문구_파일이_비어_있지_않다():
    assert _limit_text()


def test_켬_최후_통지면_보정_프롬프트에_제한을_넣고_결과에_표시한다():
    out, prompts = _run("final", ON)
    assert all(_limit_text() in p for p in prompts)
    assert out.amendment_limit_applied is True
    assert all(d.amendment_limit.value == AmendmentLimit.FINAL for d in out.directions)
    assert all(NOTICE_KIND_CHECK not in checks for checks in _checks(out))


def test_켬_통지_종류를_모르면_확인_필요로_둔다():
    out, prompts = _run("unknown", ON)
    assert all(_limit_text() not in p for p in prompts)  # 모르는데 제한을 적용하지 않는다
    assert out.amendment_limit_applied is False
    assert Flag.NEEDS_HUMAN_REVIEW in out.flags
    assert all(Flag.NEEDS_HUMAN_REVIEW in d.flags for d in out.directions)
    assert all(d.amendment_limit.value is None for d in out.directions)
    assert all(NOTICE_KIND_CHECK in checks for checks in _checks(out))


def test_켬_최초_통지면_제한이_없다():
    out, prompts = _run("initial", ON)
    assert all(_limit_text() not in p for p in prompts)
    assert out.amendment_limit_applied is False
    # (초안 쪽 표시는 법률 근거 미확인 때문에 늘 있어, 방향 후보 결과의 표시로 본다)
    assert all(Flag.NEEDS_HUMAN_REVIEW not in d.flags for d in out.directions)
    assert all(NOTICE_KIND_CHECK not in checks for checks in _checks(out))


def test_끔_통지_종류를_모르면_지금_동작_그대로():
    out, prompts = _run("unknown", OFF)
    assert all(_limit_text() not in p for p in prompts)
    assert out.amendment_limit_applied is False
    assert all(NOTICE_KIND_CHECK not in checks for checks in _checks(out))
    assert all(NOTICE_FINAL_UNLIMITED not in checks for checks in _checks(out))
    assert all(d.amendment_limit.value is None for d in out.directions)
    assert all(Flag.NEEDS_HUMAN_REVIEW not in d.flags for d in out.directions)


def test_끔_최후_통지면_제한을_넣지_않고_직접_검토_표시를_더한다():
    out, prompts = _run("final", OFF)
    assert all(_limit_text() not in p for p in prompts)
    assert out.amendment_limit_applied is False
    # 보정 제한 칸은 스위치와 상관없이 통지 종류 사실 그대로
    assert all(d.amendment_limit.value == AmendmentLimit.FINAL for d in out.directions)
    assert all(NOTICE_KIND_CHECK not in checks for checks in _checks(out))
    # 제한을 안 넣은 초안이라는 사실을 후보마다 확인 사항과 직접 검토 표시로 남긴다
    assert all(NOTICE_FINAL_UNLIMITED in checks for checks in _checks(out))
    assert all(Flag.NEEDS_HUMAN_REVIEW in d.flags for d in out.directions)


def test_켬_최후_통지면_제한_없음_표시를_붙이지_않는다():
    out, _ = _run("final", ON)
    assert all(NOTICE_FINAL_UNLIMITED not in checks for checks in _checks(out))
