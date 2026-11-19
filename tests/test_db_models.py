"""DB 모델(표 정의)을 DB 없이 본다. 이슈 #55 task 1·2.

실제 Postgres에서 도는지는 마이그레이션 테스트(test_db_migrations.py, CI)가 본다.
"""

import re

from sqlalchemy import CheckConstraint, Date, DateTime, UniqueConstraint

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


def _table(name):
    return Base.metadata.tables[name]


def _check_sql(table_name, constraint_name):
    """이름으로 CHECK 제약의 SQL 글자를 찾는다."""
    for c in _table(table_name).constraints:
        if isinstance(c, CheckConstraint) and c.name == constraint_name:
            return str(c.sqltext)
    raise AssertionError(f"{table_name}에 CHECK {constraint_name}이 없다")


def _unique_column_sets(table_name):
    """unique 제약·unique 인덱스·unique 칸마다 칸 이름 묶음."""
    t = _table(table_name)
    sets = [
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
    for name in CASE_TABLES:
        t = _table(name)
        date_cols = {c.name for c in t.columns if isinstance(c.type, Date | DateTime)}
        for cols in _unique_column_sets(name):
            assert not (cols & date_cols), f"{name}: {cols}"
