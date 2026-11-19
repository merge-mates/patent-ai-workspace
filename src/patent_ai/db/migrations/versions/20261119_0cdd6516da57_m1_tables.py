"""m1 tables

Revision ID: 0cdd6516da57
Revises: 57c073821f45
Create Date: 2026-11-19 15:23:19.481207

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0cdd6516da57"
down_revision: str | Sequence[str] | None = "57c073821f45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """M1 표 17개 (이슈 #55, docs/data-model.md 5절) + 기본 사용자 한 명.

    묶는 칸: cases.application_number(출원번호) + case_events.doc_number(발송번호·접수번호).
    날짜 칸은 어떤 unique에도 넣지 않는다.
    """
    op.create_table(
        "api_cache",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "result_inputs",
        sa.Column("result_id", sa.Text(), nullable=False),
        sa.Column("input_kind", sa.Text(), nullable=False),
        sa.Column("input_id", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "input_kind IN ('result', 'document')", name="ck_result_inputs_input_kind"
        ),
        sa.PrimaryKeyConstraint("result_id", "input_kind", "input_id"),
    )
    op.create_index(
        "ix_result_inputs_input", "result_inputs", ["input_kind", "input_id"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 로그인이 없어 모든 요청은 이 사용자로 처리한다 (docs/api/README.md). autogenerate가 안 넣는 것
    op.execute("INSERT INTO users (id, name) VALUES ('u_default', '기본 사용자')")
    op.create_table(
        "cases",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("application_number", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_cases_application_number",
        "cases",
        ["application_number"],
        unique=True,
        postgresql_where=sa.text("application_number IS NOT NULL"),
    )
    op.create_table(
        "case_events",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("doc_number", sa.Text(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('oa', 'amendment', 'opinion', 'registration_decision', "
            "'rejection_decision', 'other')",
            name="ck_case_events_kind",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id", "kind", "doc_number", name="uq_case_events_case_kind_number"
        ),
    )
    op.create_index(op.f("ix_case_events_case_id"), "case_events", ["case_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_event_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("processed_path", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('uploaded', 'api')", name="ck_documents_source"),
        sa.ForeignKeyConstraint(
            ["case_event_id"],
            ["case_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "sha256", name="uq_documents_case_sha256"),
    )
    op.create_index(op.f("ix_documents_case_id"), "documents", ["case_id"], unique=False)
    op.create_table(
        "cited_references",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "number", name="uq_cited_references_case_number"),
    )
    op.create_table(
        "claim_versions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_doc_number", sa.Text(), nullable=True),
        sa.Column("case_event_id", sa.Text(), nullable=True),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind <> 'amendment' OR source_doc_number IS NOT NULL",
            name="ck_claim_versions_amendment_doc_number",
        ),
        sa.CheckConstraint(
            "source_kind IN ('application', 'amendment', 'publication', 'registration')",
            name="ck_claim_versions_source_kind",
        ),
        sa.ForeignKeyConstraint(
            ["case_event_id"],
            ["case_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "version", name="uq_claim_versions_case_version"),
    )
    op.create_index(op.f("ix_claim_versions_case_id"), "claim_versions", ["case_id"], unique=False)
    op.create_table(
        "claims",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("claim_version_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("is_independent", sa.Boolean(), nullable=False),
        sa.Column(
            "depends_on",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_version_id", "number", name="uq_claims_version_number"),
    )
    op.create_table(
        "oas",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_event_id", sa.Text(), nullable=False),
        sa.Column("examined_claim_version_id", sa.Text(), nullable=True),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_event_id"],
            ["case_events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["examined_claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_event_id"),
    )
    op.create_index(op.f("ix_oas_case_id"), "oas", ["case_id"], unique=False)
    op.create_table(
        "rejections",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("oa_id", sa.Text(), nullable=False),
        sa.Column("no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("article", sa.Text(), nullable=True),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('novelty', 'inventive_step', 'clarity', 'other')", name="ck_rejections_kind"
        ),
        sa.ForeignKeyConstraint(
            ["oa_id"],
            ["oas.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("oa_id", "no", name="uq_rejections_oa_no"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("oa_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="queued", nullable=False),
        sa.Column("current_step", sa.Text(), nullable=True),
        sa.Column("waiting_for", sa.Text(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'waiting_for_human', 'succeeded', 'failed', "
            "'cancelled')",
            name="ck_runs_state",
        ),
        sa.ForeignKeyConstraint(
            ["oa_id"],
            ["oas.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_oa_id_created_at", "runs", ["oa_id", "created_at"], unique=False)
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("step_kind", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("result_status", sa.Text(), nullable=True),
        sa.Column("result_id", sa.Text(), nullable=True),
        sa.Column("model_call_count", sa.Integer(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("from_cache", sa.Boolean(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("transport_try", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'failed', 'waiting', 'cache_hit', 'transport_error', "
            "'limit_exceeded', 'invalid_output')",
            name="ck_agent_steps_outcome",
        ),
        sa.CheckConstraint(
            "step_kind IN ('code_tool', 'fixed_stage', 'decide', 'check', 'model_call')",
            name="ck_agent_steps_step_kind",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_steps_run_id"), "agent_steps", ["run_id"], unique=False)
    op.create_table(
        "case_materials",
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
        ),
        sa.PrimaryKeyConstraint("case_id"),
    )
    op.create_table(
        "oa_results",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("oa_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('ai_generated', 'ai_default', 'human_selected', 'human_edited')",
            name="ck_oa_results_origin",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'unverified', 'not_found_in_scope', 'conflict')",
            name="ck_oa_results_status",
        ),
        sa.ForeignKeyConstraint(
            ["oa_id"],
            ["oas.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oa_results_oa_id_created_at", "oa_results", ["oa_id", "created_at"], unique=False
    )
    op.create_table(
        "rejection_citations",
        sa.Column("rejection_id", sa.Text(), nullable=False),
        sa.Column("cited_reference_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "cited_paragraphs",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cited_reference_id"],
            ["cited_references.id"],
        ),
        sa.ForeignKeyConstraint(
            ["rejection_id"],
            ["rejections.id"],
        ),
        sa.PrimaryKeyConstraint("rejection_id", "cited_reference_id"),
    )
    op.create_table(
        "rejection_claims",
        sa.Column("rejection_id", sa.Text(), nullable=False),
        sa.Column("claim_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rejection_id"],
            ["rejections.id"],
        ),
        sa.PrimaryKeyConstraint("rejection_id", "claim_number"),
    )


def downgrade() -> None:
    """이 마이그레이션의 표 17개만 지운다 (조각 표 law_chunks·cite_chunks는 그대로)."""
    op.drop_table("rejection_claims")
    op.drop_table("rejection_citations")
    op.drop_index("ix_oa_results_oa_id_created_at", table_name="oa_results")
    op.drop_table("oa_results")
    op.drop_table("case_materials")
    op.drop_index(op.f("ix_agent_steps_run_id"), table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_runs_oa_id_created_at", table_name="runs")
    op.drop_table("runs")
    op.drop_table("rejections")
    op.drop_index(op.f("ix_oas_case_id"), table_name="oas")
    op.drop_table("oas")
    op.drop_table("claims")
    op.drop_index(op.f("ix_claim_versions_case_id"), table_name="claim_versions")
    op.drop_table("claim_versions")
    op.drop_table("cited_references")
    op.drop_index(op.f("ix_documents_case_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_case_events_case_id"), table_name="case_events")
    op.drop_table("case_events")
    op.drop_index(
        "uq_cases_application_number",
        table_name="cases",
        postgresql_where=sa.text("application_number IS NOT NULL"),
    )
    op.drop_table("cases")
    op.drop_table("users")
    op.drop_index("ix_result_inputs_input", table_name="result_inputs")
    op.drop_table("result_inputs")
    op.drop_table("api_cache")
