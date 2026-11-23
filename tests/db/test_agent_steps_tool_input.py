"""agent_steps의 unit_id·tool_input 두 칸 왕복 (make test-db, 이슈 #309). 끝에 되돌린다."""

import pytest
from sqlalchemy import select

from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.runs.step_log_pg import PostgresStepRecorder
from patent_ai.db.models import AgentStep
from tests.core.runs.test_store_db import _new_run, factory  # noqa: F401

pytestmark = pytest.mark.db


def _rows(factory, rid):  # noqa: F811
    with factory() as other:
        return list(
            other.scalars(select(AgentStep).where(AgentStep.run_id == rid).order_by(AgentStep.id))
        )


def test_unit_id와_tool_input을_쓰고_다른_세션에서_읽는다(factory):  # noqa: F811
    _, rid = _new_run(factory, "db_toolin_" + "a" * 20)
    tool_input = {"query": "수조", "k": 3, "element_no": 2, "citation": "D1"}
    PostgresStepRecorder(factory).record(
        StepRecord(
            run_id=rid,
            step_kind="code_tool",
            tool_name="recheck.search_vector",
            reason="다시 찾기 도구",
            outcome="ok",
            result_id="p1,p2",
            unit_id="oa_1:29-2:c1",
            tool_input=tool_input,
        )
    )
    (row,) = _rows(factory, rid)
    assert row.unit_id == "oa_1:29-2:c1"
    assert row.tool_input == tool_input
    assert row.result_id == "p1,p2"


def test_두_칸을_안_주면_NULL로_남는다_옛_줄과_같다(factory):  # noqa: F811
    _, rid = _new_run(factory, "db_toolin_" + "b" * 20)
    PostgresStepRecorder(factory).record(
        StepRecord(run_id=rid, step_kind="code_tool", tool_name="run_f3", reason="x", outcome="ok")
    )
    (row,) = _rows(factory, rid)
    assert row.unit_id is None and row.tool_input is None
