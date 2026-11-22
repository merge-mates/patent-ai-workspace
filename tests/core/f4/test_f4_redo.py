"""사람 방향 선택 뒤 초안만 다시 만들기 (이슈 #70 ①-3).

방향 후보(모델 호출)는 앞 실행 것을 그대로 쓰고 선택만 바꿔 의견서·보정을 다시 만든다.
"""

import pytest

from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import redo_drafts
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.schemas.common import Flag, Origin
from patent_ai.core.schemas.direction import DirectionSelection
from tests.core.f4.test_f4_run import UNIT_CLARITY, UNIT_INVENTIVE, _clean_case, _run, _transport

LOW_PICK = f"{UNIT_CLARITY}:d2"  # amend_only: 명확성 의견서·보정 녹화 답과 모양이 맞는 후보


def _held_prev():
    """확신 낮은 묶음(명확성)이 선택 없이 보류된 앞 실행 결과."""
    data = _clean_case()
    prev, _ = _run(
        data,
        directions=("direction_inventive", "direction_low"),
        opinions=("opinion_inventive",),
        amendments=("amendment_inventive",),
    )
    assert prev.held_units == [UNIT_CLARITY]
    return data, prev


def _redo(data, prev, selections, opinions=(), amendments=()):
    transport = _transport((), opinions, amendments)
    ctx = RunContext(
        run_id="r_2", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    out = redo_drafts(F4Input.model_validate(data), prev, selections, ctx=ctx)
    return out, transport


def _pick(cid: str) -> DirectionSelection:
    return DirectionSelection(candidate_id=cid, origin=Origin.HUMAN_SELECTED)


def test_사람이_고르면_보류했던_묶음_초안이_생기고_방향_후보는_다시_부르지_않는다():
    data, prev = _held_prev()

    out, transport = _redo(
        data,
        prev,
        {UNIT_CLARITY: _pick(LOW_PICK)},
        opinions=("opinion_inventive", "opinion_clarity"),
        amendments=("amendment_inventive", "amendment_clarity"),
    )

    assert out.held_units == []
    assert (UNIT_CLARITY, LOW_PICK) in [(b.unit_id, b.candidate_id) for b in out.drafts.based_on]
    # 방향 후보 단계(f4.direction)는 부르지 않는다
    assert "f4.direction" not in [c["step"] for c in transport.calls]
    by_unit = {d.unit_id: d for d in out.directions}
    assert by_unit[UNIT_CLARITY].selection == _pick(LOW_PICK)
    # 다른 묶음의 선택(AI 기본값)과 모든 후보는 앞 실행 그대로
    assert by_unit[UNIT_INVENTIVE] == {d.unit_id: d for d in prev.directions}[UNIT_INVENTIVE]
    assert [d.candidates for d in out.directions] == [d.candidates for d in prev.directions]
    assert Flag.NEEDS_HUMAN_JUDGMENT not in out.drafts.flags


def test_직접_쓴_방향은_AI가_초안을_만들지_않고_보류로_남는다():
    data, prev = _held_prev()
    written = DirectionSelection(
        written_direction="청구항 2 문구를 고쳐 명확히", origin=Origin.HUMAN_WRITTEN
    )

    out, transport = _redo(
        data,
        prev,
        {UNIT_CLARITY: written},
        opinions=("opinion_inventive",),
        amendments=("amendment_inventive",),
    )

    assert out.held_units == [UNIT_CLARITY]
    assert {d.unit_id: d for d in out.directions}[UNIT_CLARITY].selection == written
    # 명확성 묶음 의견서·보정은 부르지 않았다 (발명 묶음 것만 한 번씩)
    assert [c["step"] for c in transport.calls] == ["f4.opinion", "f4.amendment"]


def test_후보_밖_id를_고르면_멈춘다():
    data, prev = _held_prev()
    with pytest.raises(ValueError, match="후보"):
        _redo(data, prev, {UNIT_CLARITY: _pick(f"{UNIT_CLARITY}:d9")})


def test_없는_묶음을_고르면_멈춘다():
    data, prev = _held_prev()
    with pytest.raises(ValueError, match="묶음"):
        _redo(data, prev, {"oa_1:없음:c9": _pick("x")})


def test_다른_OA의_앞_결과로는_다시_만들지_않는다():
    data, prev = _held_prev()
    other = prev.model_copy(update={"oa_id": "oa_2"})
    with pytest.raises(ValueError, match="OA"):
        _redo(data, other, {UNIT_CLARITY: _pick(LOW_PICK)})
