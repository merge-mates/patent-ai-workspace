"""DB 모델(표 정의)을 DB 없이 본다. 이슈 #55 task 1·2.

실제 Postgres에서 도는지는 마이그레이션 테스트(test_db_migrations.py, CI)가 본다.
"""

import dataclasses
import re
from typing import get_args

from sqlalchemy import CheckConstraint, Date, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.cases.human_inputs import HumanInputKind
from patent_ai.core.llm.limits import CallRecord
from patent_ai.core.runs.store import RunKind
from patent_ai.core.schemas.common import Origin, StatusValue
from patent_ai.core.schemas.oa_result import RejectionKind
from patent_ai.db import models  # noqa: F401  (표를 Base.metadata에 올린다)
from patent_ai.db.base import Base
from patent_ai.db.ids import new_id

CASE_TABLES = {
    "users",
    "cases",
    "case_events",
    "documents",
    "claim_versions",
    "claims",
    "oas",
}
RESULT_TABLES = {
    "rejections",
    "cited_references",
    "rejection_claims",
    "rejection_citations",
    "oa_results",
    "case_materials",
    "runs",
    "agent_steps",
    "result_inputs",
    "api_cache",
    "direction_selections",
    "human_inputs",
}
M1_TABLES = CASE_TABLES | RESULT_TABLES
# API 명세(docs/api/README.md)의 실행 상태 state
RUN_STATES = {"queued", "running", "waiting_for_human", "succeeded", "failed", "cancelled"}


def _table(name):
    return Base.metadata.tables[name]


def _check_sql(table_name, constraint_name):
    """이름으로 CHECK 제약의 SQL 글자를 찾는다."""
    for c in _table(table_name).constraints:
        if isinstance(c, CheckConstraint) and c.name == constraint_name:
            return str(c.sqltext)
    raise AssertionError(f"{table_name}에 CHECK {constraint_name}이 없다")


def _check_values(table_name, constraint_name):
    """`x IN ('a', 'b')` 꼴 CHECK에서 따옴표 안 값들."""
    return set(re.findall(r"'([^']*)'", _check_sql(table_name, constraint_name)))


def _unique_column_sets(table_name):
    """기본 키·unique 제약·unique 인덱스·unique 칸마다 칸 이름 묶음."""
    t = _table(table_name)
    sets = [{col.name for col in t.primary_key.columns}]
    sets += [
        {col.name for col in c.columns} for c in t.constraints if isinstance(c, UniqueConstraint)
    ]
    sets += [{col.name for col in i.columns} for i in t.indexes if i.unique]
    sets += [{col.name} for col in t.columns if col.unique]
    return sets


def test_case_tables_exist():
    assert CASE_TABLES <= set(Base.metadata.tables)


def test_new_id_has_kind_prefix_and_is_random():
    a, b = new_id("c"), new_id("c")

    assert re.fullmatch(r"c_[0-9a-f]{32}", a)
    assert a != b


def test_cases_application_number_unique_only_when_present():
    # 출원번호를 읽기 전 임시 사건은 비어 있어도 되고 여럿일 수 있다
    t = _table("cases")
    assert t.c.application_number.nullable
    assert t.c.user_id.foreign_keys

    idx = [
        i for i in t.indexes if i.unique and {c.name for c in i.columns} == {"application_number"}
    ]
    assert len(idx) == 1
    where = idx[0].dialect_options["postgresql"]["where"]
    assert "application_number IS NOT NULL" in str(where)


def test_case_events_bundle_by_case_kind_and_doc_number():
    # OA는 발송번호, 보정서는 접수번호가 doc_number. 같은 사건에 같은 번호는 한 줄
    assert {"case_id", "kind", "doc_number"} in _unique_column_sets("case_events")


def test_case_events_kind_values():
    sql = _check_sql("case_events", "ck_case_events_kind")
    for kind in (
        "oa",
        "amendment",
        "opinion",
        "registration_decision",
        "rejection_decision",
        "other",
    ):
        assert f"'{kind}'" in sql


def test_oas_one_per_case_event_and_examined_version_may_be_unknown():
    t = _table("oas")
    assert {"case_event_id"} in _unique_column_sets("oas")
    assert not t.c.case_event_id.nullable
    # 심사 대상 판을 모르면 비워 두고 "확인되지 않음"으로 본다
    assert t.c.examined_claim_version_id.nullable


def test_documents_same_file_once_per_case():
    t = _table("documents")
    for col in ("path", "sha256", "source", "received_at"):
        assert not t.c[col].nullable
    assert {"case_id", "sha256"} in _unique_column_sets("documents")
    sql = _check_sql("documents", "ck_documents_source")
    assert "'uploaded'" in sql and "'api'" in sql


def test_claim_versions_source_kind_values():
    sql = _check_sql("claim_versions", "ck_claim_versions_source_kind")
    for kind in ("application", "amendment", "publication", "registration"):
        assert f"'{kind}'" in sql
    assert not _table("claim_versions").c.source_kind.nullable


def test_claim_versions_amendment_needs_receipt_number():
    sql = _check_sql("claim_versions", "ck_claim_versions_amendment_doc_number")
    assert "amendment" in sql and "source_doc_number IS NOT NULL" in sql


def test_claim_versions_and_claims_numbering_unique():
    assert {"case_id", "version"} in _unique_column_sets("claim_versions")
    assert {"claim_version_id", "number"} in _unique_column_sets("claims")


def test_no_date_column_in_any_unique_key():
    # 날짜만으로 묶거나 합치지 않는다 (CLAUDE.md 특허 도메인 규칙, 이슈 #55 합격 기준 3)
    for name in M1_TABLES:
        t = _table(name)
        date_cols = {c.name for c in t.columns if isinstance(c.type, Date | DateTime)}
        for cols in _unique_column_sets(name):
            assert not (cols & date_cols), f"{name}: {cols}"


# --- task 2: 거절이유·결과·실행 표 ---


def test_result_tables_exist():
    assert RESULT_TABLES <= set(Base.metadata.tables)


def test_rejections_kind_matches_code_and_numbered_per_oa():
    assert _check_values("rejections", "ck_rejections_kind") == {k.value for k in RejectionKind}
    assert {"oa_id", "no"} in _unique_column_sets("rejections")


def test_rejection_links_are_one_row_per_pair():
    # 대상 청구항은 OA 당시 번호로 담는다 (그 판의 claims 줄이 아직 없을 수 있다)
    assert {"rejection_id", "claim_number"} in _unique_column_sets("rejection_claims")
    assert {"rejection_id", "cited_reference_id"} in _unique_column_sets("rejection_citations")
    assert {"case_id", "number"} in _unique_column_sets("cited_references")


def test_oa_results_body_is_jsonb_with_status_origin_columns():
    t = _table("oa_results")
    assert isinstance(t.c.body.type, JSONB)
    for col in ("oa_id", "run_id", "status", "origin"):
        assert not t.c[col].nullable
    assert _check_values("oa_results", "ck_oa_results_status") == {s.value for s in StatusValue}
    # human_written은 방향 선택(selection.origin)에만 쓰고 결과 맨 위 origin에는 오지 않는다
    assert _check_values("oa_results", "ck_oa_results_origin") == {
        o.value for o in Origin if o != Origin.HUMAN_WRITTEN
    }


def test_oa_results_has_index_for_latest_per_oa():
    # OA마다 가장 최근 succeeded 결과를 고를 때 쓴다 (고르는 코드는 #56)
    idx = [[c.name for c in i.columns] for i in _table("oa_results").indexes]
    assert ["oa_id", "created_at"] in idx


def test_case_materials_one_row_per_case():
    t = _table("case_materials")
    assert [c.name for c in t.primary_key.columns] == ["case_id"]
    assert isinstance(t.c.body.type, JSONB)


def test_runs_state_matches_api():
    assert _check_values("runs", "ck_runs_state") == RUN_STATES
    assert not _table("runs").c.oa_id.nullable


def test_runs_kind_matches_core_and_defaults_to_full():
    # 실행 종류: 끝까지 도는 실행 / 사람 선택 뒤 초안만 다시 만드는 작은 실행 (#70)
    assert _check_values("runs", "ck_runs_kind") == set(get_args(RunKind))
    col = _table("runs").c.kind
    assert not col.nullable
    assert "full" in str(col.server_default.arg)


def test_direction_selections_hold_human_choice_only():
    # 사람이 고른 것·직접 쓴 것만 남긴다 (AI 기본값은 결과 안 selection에 있음, #70)
    t = _table("direction_selections")
    # run_id: 이 선택을 적용할 작은 실행 (그 실행만 이 선택을 쓴다)
    for col in ("oa_id", "run_id", "unit_id", "origin", "created_at"):
        assert not t.c[col].nullable
    assert t.c.candidate_id.nullable and t.c.written_direction.nullable
    assert _check_values("direction_selections", "ck_direction_selections_origin") == {
        Origin.HUMAN_SELECTED.value,
        Origin.HUMAN_WRITTEN.value,
    }
    one_of = _check_sql("direction_selections", "ck_direction_selections_one_of")
    assert "candidate_id" in one_of and "written_direction" in one_of
    idx = [[c.name for c in i.columns] for i in t.indexes]
    assert ["run_id"] in idx and ["oa_id", "unit_id", "created_at"] in idx


def test_agent_steps_hold_step_record_and_call_record():
    cols = set(_table("agent_steps").c.keys())
    assert set(StepRecord.model_fields) <= cols
    # CallRecord.step은 tool_name 칸에 담는다
    call_fields = {f.name for f in dataclasses.fields(CallRecord)} - {"step"}
    assert call_fields <= cols
    kinds = _check_values("agent_steps", "ck_agent_steps_step_kind")
    assert set(get_args(StepRecord.model_fields["step_kind"].annotation)) | {"model_call"} == kinds


def test_agent_steps_outcome_covers_both_records():
    outcomes = _check_values("agent_steps", "ck_agent_steps_outcome")
    assert set(get_args(StepRecord.model_fields["outcome"].annotation)) <= outcomes
    assert {"ok", "cache_hit", "transport_error", "limit_exceeded", "invalid_output"} <= outcomes
    # 잘린 답(stop_reason = max_tokens)은 모양이 틀린 답과 다른 이유로 남는다 (#172)
    assert "output_truncated" in outcomes


def test_agent_steps_has_stop_reason_for_model_calls():
    # 모델이 답을 끝낸 이유 (end_turn·max_tokens 등). 옛 기록은 NULL (#172)
    col = _table("agent_steps").c["stop_reason"]
    assert col.nullable


def test_agent_steps_has_invalid_kind_for_model_calls():
    # 출력 검사에 떨어진 오류 종류 (짧은 코드). 검사를 통과했거나 옛 기록은 NULL (#228)
    assert _table("agent_steps").c["invalid_kind"].nullable


def test_result_inputs_point_to_result_or_document():
    key = {"result_id", "input_kind", "input_id"}
    assert key in _unique_column_sets("result_inputs")
    assert _check_values("result_inputs", "ck_result_inputs_input_kind") == {"result", "document"}


def test_api_cache_key_is_primary_and_value_jsonb():
    t = _table("api_cache")
    assert [c.name for c in t.primary_key.columns] == ["key"]
    assert isinstance(t.c.value.type, JSONB)


def test_core_이력_종류는_case_events_kind_CHECK와_같음():
    # 사건 묶기(core)의 이력 종류가 DB CHECK와 어긋나면 저장할 때 깨진다 (#16 T5)
    from patent_ai.core.f1_oa_reader.case_grouping import HistoryKind

    assert set(get_args(HistoryKind)) == _check_values("case_events", "ck_case_events_kind")


def test_core_청구항_판_종류는_source_kind_CHECK와_같음():
    from patent_ai.core.f1_oa_reader.case_repository import SourceKind

    assert set(get_args(SourceKind)) == _check_values(
        "claim_versions", "ck_claim_versions_source_kind"
    )


def test_보정서_판은_이력_줄이_꼭_있음():
    # #120 리뷰 (가): 보정서 판인데 case_event_id가 비면 DB가 막는다 (#16 T6)
    sql = _check_sql("claim_versions", "ck_claim_versions_amendment_event")
    assert "case_event_id IS NOT NULL" in sql


def test_human_inputs_kind_matches_core_and_only_numbers_have_value():
    # 사람이 넣은 번호·"맞아요" (#70 계획 ②). 확인은 값이 없고 번호는 값이 있다
    assert _check_values("human_inputs", "ck_human_inputs_kind") == set(get_args(HumanInputKind))
    assert "value IS NULL" in _check_sql("human_inputs", "ck_human_inputs_value")
    t = _table("human_inputs")
    for col in ("oa_id", "run_id", "kind", "created_at"):
        assert not t.c[col].nullable
    assert ["run_id"] in [[c.name for c in i.columns] for i in t.indexes]
