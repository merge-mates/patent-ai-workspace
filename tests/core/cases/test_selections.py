"""사람 방향 선택 기록 저장소 (메모리 fake, 이슈 #70 ①-2)."""

from datetime import UTC, datetime, timedelta

import pytest

from patent_ai.core.cases.selections import InMemorySelectionStore
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.direction import DirectionSelection

T0 = datetime(2099, 1, 1, tzinfo=UTC)


def _clock():
    t = [T0]

    def tick():
        t[0] += timedelta(seconds=1)
        return t[0]

    return tick


def _pick(cid: str) -> DirectionSelection:
    return DirectionSelection(candidate_id=cid, origin=Origin.HUMAN_SELECTED)


def _write(text: str) -> DirectionSelection:
    return DirectionSelection(written_direction=text, origin=Origin.HUMAN_WRITTEN)


def test_저장하면_묶음마다_가장_최근_선택이_나온다():
    store = InMemorySelectionStore(clock=_clock())
    store.save_selection("oa_1", "u1", _pick("c1"))
    store.save_selection("oa_1", "u1", _write("청구항 1에 한정 추가"))
    store.save_selection("oa_1", "u2", _pick("c9"))

    latest = store.latest_selections("oa_1")

    assert latest == {"u1": _write("청구항 1에 한정 추가"), "u2": _pick("c9")}


def test_다른_OA의_선택은_섞이지_않는다():
    store = InMemorySelectionStore(clock=_clock())
    store.save_selection("oa_1", "u1", _pick("c1"))

    assert store.latest_selections("oa_2") == {}


def test_AI_기본값은_사람_선택_기록에_넣지_않는다():
    store = InMemorySelectionStore(clock=_clock())

    with pytest.raises(ValueError, match="사람"):
        store.save_selection(
            "oa_1", "u1", DirectionSelection(candidate_id="c1", origin=Origin.AI_DEFAULT)
        )
    assert store.latest_selections("oa_1") == {}


def test_시각이_같으면_나중에_넣은_것이_이긴다():
    store = InMemorySelectionStore(clock=lambda: T0)
    store.save_selection("oa_1", "u1", _pick("c1"))
    store.save_selection("oa_1", "u1", _pick("c2"))

    assert store.latest_selections("oa_1") == {"u1": _pick("c2")}
