"""recheck_stats 테스트: F3Result.recheck_log에서 도구 쓰임을 센다 (지어낸 예측, 원문 없음).

기대값은 구현 계획 m3-i2-309b task-5와 recheck design 7-2 (도구 호출 수, give_up 비율).
"""

import json

from f3_eval_builder import UNIT, prediction, write_run

from eval.f3.recheck_stats import recheck_stats


def _row(outcome, tool_calls, turns, no=1):
    return {
        "unit_id": UNIT,
        "claim": 1,
        "element_claim": 1,
        "element_no": no,
        "citation": "D1",
        "doc_id": "KR20990000001A",
        "mode": "agent",
        "judge": "compare",
        "outcome": outcome,
        "tool_calls": tool_calls,
        "turns": turns,
        "queries": [],
        "submitted_ids": [],
        "reason": None,
        "steps": [],
    }


def _pred(rows):
    return {**prediction(), "recheck_log": rows}


def test_도구_호출과_차례_수의_평균_최대를_센다(tmp_path):
    rows = [_row("submitted", 2, 3), _row("gave_up", 4, 5, 2), _row("limit_reached", 6, 7, 3)]
    write_run(tmp_path, _pred(rows))
    s = recheck_stats(tmp_path)
    assert s["components"] == 3
    assert s["tool_calls_mean"] == 4.0 and s["tool_calls_max"] == 6
    assert s["turns_mean"] == 5.0 and s["turns_max"] == 7


def test_끝_상태별_수와_give_up_비율을_센다(tmp_path):
    rows = [_row("submitted", 1, 1), _row("gave_up", 1, 1, 2), _row("gave_up", 1, 1, 3)]
    rows.append(_row("tool_failed", 1, 1, 4))
    write_run(tmp_path, _pred(rows))
    s = recheck_stats(tmp_path)
    assert s["outcomes"] == {
        "submitted": 1,
        "gave_up": 2,
        "limit_reached": 0,
        "model_call_failed": 0,
        "tool_failed": 1,
    }
    assert s["give_up_rate"] == 0.5


def test_예측이_여러_개면_합쳐서_센다(tmp_path):
    write_run(tmp_path, _pred([_row("submitted", 2, 2)]))
    write_run(tmp_path, _pred([_row("gave_up", 4, 2)]), key="1020990000002_952099000000002")
    s = recheck_stats(tmp_path)
    assert s["components"] == 2 and s["tool_calls_mean"] == 3.0 and s["give_up_rate"] == 0.5


def test_recheck_log_칸이_없는_옛_예측은_0건이고_평균은_None(tmp_path):
    write_run(tmp_path, prediction())
    s = recheck_stats(tmp_path)
    assert s["components"] == 0
    assert s["tool_calls_mean"] is None and s["give_up_rate"] is None
    assert json.dumps(s)  # scores 옆에 JSON으로 낼 수 있다
