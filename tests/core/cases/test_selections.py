"""사람 방향 선택 기록 저장소 (메모리 fake, 이슈 #70 ①-2).

선택 한 줄은 그 선택을 적용할 작은 실행(redo_drafts) 하나에 묶는다. 실행은 자기에게 묶인 선택만
쓴다: 다시 돌린(full) 뒤 옛 선택이 새 후보 위에 되살아나지 않게 (#70 리뷰 막음).
"""

from datetime import UTC, datetime

import pytest

from patent_ai.core.cases.selections import InMemorySelectionStore
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.direction import DirectionSelection

T0 = datetime(2099, 1, 1, tzinfo=UTC)


def _pick(cid: str) -> DirectionSelection:
    return DirectionSelection(candidate_id=cid, origin=Origin.HUMAN_SELECTED)


def _write(text: str) -> DirectionSelection:
    return DirectionSelection(written_direction=text, origin=Origin.HUMAN_WRITTEN)


def test_실행은_자기에게_묶인_선택만_읽는다():
    store = InMemorySelectionStore(clock=lambda: T0)
    store.save_selection("oa_1", "u1", _pick("c1"), run_id="r_1")
    store.save_selection("oa_1", "u2", _write("청구항 1에 한정 추가"), run_id="r_2")

    assert store.selections_for_run("r_1") == {"u1": _pick("c1")}
    assert store.selections_for_run("r_2") == {"u2": _write("청구항 1에 한정 추가")}
    assert store.selections_for_run("r_없음") == {}


def test_AI_기본값은_사람_선택_기록에_넣지_않는다():
    store = InMemorySelectionStore(clock=lambda: T0)

    with pytest.raises(ValueError, match="사람"):
        store.save_selection(
            "oa_1",
            "u1",
            DirectionSelection(candidate_id="c1", origin=Origin.AI_DEFAULT),
            run_id="r_1",
        )
    assert store.selections_for_run("r_1") == {}
