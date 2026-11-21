"""거절이유·결과 표 (이슈 #55 task 2, docs/data-model.md 5절).

원본은 결과 표(oa_results·case_materials)의 본문 jsonb다. 거절이유 엔티티 표 4개는 M1에서
빈 채로 두고, M2에서 F3가 청구항·인용문헌으로 찾아야 할 때 결과에서 채운다.
같은 OA를 여러 번 돌리면 앞 결과를 지우지 않고, OA마다 가장 최근 succeeded 결과를 보인다.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from patent_ai.db.base import Base
from patent_ai.db.ids import id_factory

# core/schemas/common.py의 StatusValue·Origin과 같은 값 (테스트가 비교한다)
_STATUS_CHECK = "status IN ('confirmed', 'unverified', 'not_found_in_scope', 'conflict')"
_ORIGIN_CHECK = "origin IN ('ai_generated', 'ai_default', 'human_selected', 'human_edited')"


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --- 거절이유 엔티티 표 (M1은 비어 있음) ---


class Rejection(Base):
    """OA의 거절이유 하나."""

    __tablename__ = "rejections"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('novelty', 'inventive_step', 'clarity', 'other')",
            name="ck_rejections_kind",
        ),
        UniqueConstraint("oa_id", "no", name="uq_rejections_oa_no"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("rej"))
    oa_id: Mapped[str] = mapped_column(ForeignKey("oas.id"))
    no: Mapped[int] = mapped_column(Integer)  # OA 거절이유 표 순번 (1부터)
    kind: Mapped[str] = mapped_column(Text)
    article: Mapped[str | None] = mapped_column(Text)  # 조문 코드 (예: 29-2)
    supported: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _created_at()


class CitedReference(Base):
    """인용문헌 하나. 사건마다 번호(키 꼴, 예: KR20990000001A)로 한 줄."""

    __tablename__ = "cited_references"
    __table_args__ = (
        UniqueConstraint("case_id", "number", name="uq_cited_references_case_number"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("ref"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    number: Mapped[str] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    published_on: Mapped[date | None]  # 표시용
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))  # 파일이 있을 때
    created_at: Mapped[datetime] = _created_at()


class RejectionClaim(Base):
    """거절이유 ↔ 대상 청구항. OA 당시 청구항 번호로 담는다."""

    __tablename__ = "rejection_claims"
    __table_args__ = (PrimaryKeyConstraint("rejection_id", "claim_number"),)

    rejection_id: Mapped[str] = mapped_column(ForeignKey("rejections.id"))
    claim_number: Mapped[int] = mapped_column(Integer)


class RejectionCitation(Base):
    """거절이유 ↔ 인용문헌 + 심사관이 지정한 위치."""

    __tablename__ = "rejection_citations"
    __table_args__ = (PrimaryKeyConstraint("rejection_id", "cited_reference_id"),)

    rejection_id: Mapped[str] = mapped_column(ForeignKey("rejections.id"))
    cited_reference_id: Mapped[str] = mapped_column(ForeignKey("cited_references.id"))
    label: Mapped[str] = mapped_column(Text)  # D1, D2…
    cited_paragraphs: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )


# --- 결과 표 (원본) ---


class OAResultRow(Base):
    """F1 결과 ① OAResult. 본문은 jsonb, 거르는 칸만 보통 칸."""

    __tablename__ = "oa_results"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_oa_results_status"),
        CheckConstraint(_ORIGIN_CHECK, name="ck_oa_results_origin"),
        # OA마다 가장 최근 결과를 찾는다 (succeeded 거르기는 runs와 이어서, #57)
        Index("ix_oa_results_oa_id_created_at", "oa_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("res"))
    oa_id: Mapped[str] = mapped_column(ForeignKey("oas.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)  # OAResult.model_dump(mode="json")
    status: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class StepResultRow(Base):
    """F3·F4 결과 (실행 하나에 단계마다 한 줄). 본문은 도구 출력 그대로 jsonb (#191).

    F3 = F3Result(판단 단위·대비표·명확성 검토), F4 = F4Output(대응 방향 후보·초안).
    결과 API는 OA의 가장 최근 보여 줄 실행(oa_results와 같은 실행)을 골라 이 표에서 읽는다.
    """

    __tablename__ = "step_results"
    __table_args__ = (
        CheckConstraint("kind IN ('f3', 'f4')", name="ck_step_results_kind"),
        CheckConstraint(_STATUS_CHECK, name="ck_step_results_status"),
        UniqueConstraint("run_id", "kind", name="uq_step_results_run_kind"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("sres"))
    oa_id: Mapped[str] = mapped_column(ForeignKey("oas.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    kind: Mapped[str] = mapped_column(Text)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)  # model_dump(mode="json")
    status: Mapped[str] = mapped_column(Text)  # body.status.value (거르는 칸)
    created_at: Mapped[datetime] = _created_at()


class CaseMaterialsRow(Base):
    """⑥ CaseMaterials. 사건마다 최신 한 줄 (실행이 끝날 때·자료가 더해질 때 다시 쓴다)."""

    __tablename__ = "case_materials"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))  # 자료만 더하면 비어 있음
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResultInput(Base):
    """뒤 결과가 기댄 앞 결과·자료. 상태 전파와 "다시 확인 필요"에 쓴다.

    가리키는 표가 여럿이라 외래 키는 걸지 않는다.
    """

    __tablename__ = "result_inputs"
    __table_args__ = (
        CheckConstraint("input_kind IN ('result', 'document')", name="ck_result_inputs_input_kind"),
        PrimaryKeyConstraint("result_id", "input_kind", "input_id"),
        # 앞 입력이 바뀌면 기댄 뒤 결과를 찾는다
        Index("ix_result_inputs_input", "input_kind", "input_id"),
    )

    result_id: Mapped[str] = mapped_column(Text)
    input_kind: Mapped[str] = mapped_column(Text)
    input_id: Mapped[str] = mapped_column(Text)
