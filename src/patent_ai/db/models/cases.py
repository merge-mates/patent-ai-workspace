"""사건·서류 표 7개 (이슈 #55 task 1, docs/data-model.md 2절·5절).

묶는 규칙: 출원번호(`cases.application_number`) + 발송번호(OA) / 접수번호(보정서)
(`case_events.doc_number`)로 묶는다. 날짜 칸은 보여 주기만 하고 어떤 unique에도 넣지 않는다.
"""

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from patent_ai.db.base import Base
from patent_ai.db.ids import id_factory


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """사용자. 로그인이 없어 M1은 기본 한 명 (마이그레이션이 넣음)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("u"))
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Case(Base):
    """사건 하나. 출원번호를 읽기 전(임시 사건)에는 application_number가 비어 있다."""

    __tablename__ = "cases"
    __table_args__ = (
        # 출원번호가 있을 때만 사건 하나 (비어 있는 임시 사건은 여럿이어도 된다)
        Index(
            "uq_cases_application_number",
            "application_number",
            unique=True,
            postgresql_where=text("application_number IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("c"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    application_number: Mapped[str | None] = mapped_column(Text)
    # 같은 출원번호 사건에 OA를 옮겨 합친 임시 사건이면 그 사건 id (#272). 목록에서 숨긴다
    merged_into_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.id", name="fk_cases_merged_into_case_id")
    )
    created_at: Mapped[datetime] = _created_at()


class CaseEvent(Base):
    """사건 이력 한 줄. OA면 doc_number = 발송번호, 보정서면 접수번호."""

    __tablename__ = "case_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('oa', 'amendment', 'opinion', 'registration_decision', "
            "'rejection_decision', 'other')",
            name="ck_case_events_kind",
        ),
        # 같은 사건에 같은 종류·번호는 한 줄. 번호를 모르면(NULL) 겹침 검사에서 빠진다
        UniqueConstraint("case_id", "kind", "doc_number", name="uq_case_events_case_kind_number"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("ev"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    doc_number: Mapped[str | None] = mapped_column(Text)
    # 행정 이력 순서 (1부터). 순서를 모르면 비우고, 그 자료는 OA 시점 자르기에서 빠진다
    seq: Mapped[int | None] = mapped_column(Integer)
    # 표시용. 묶거나 고를 때 쓰지 않는다
    event_date: Mapped[date | None]
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    """파일 하나. 원본은 디스크, DB에는 경로·해시만."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("source IN ('uploaded', 'api')", name="ck_documents_source"),
        # 같은 사건에 같은 파일은 한 번 (다시 올리면 409)
        UniqueConstraint("case_id", "sha256", name="uq_documents_case_sha256"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("doc"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    case_event_id: Mapped[str | None] = mapped_column(ForeignKey("case_events.id"))
    kind: Mapped[str] = mapped_column(Text)  # 예: oa, claims, citation (CaseDocument.kind)
    path: Mapped[str] = mapped_column(Text)
    processed_path: Mapped[str | None] = mapped_column(Text)  # 쪽 텍스트 가공본 (F1이 채움)
    sha256: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 인용문헌 본문이면 어느 인용문헌인지: OA 인용문헌 번호 값 (CaseDocument.citation_key, #201).
    # F3가 이 키로 본문 문서를 찾는다. 인용문헌이 아니거나 모르면 비운다
    citation_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class ClaimVersion(Base):
    """청구항 판. 출원서·보정서·공개공보·등록공보는 서로 다른 판이다."""

    __tablename__ = "claim_versions"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('application', 'amendment', 'publication', 'registration')",
            name="ck_claim_versions_source_kind",
        ),
        # 보정서로 생긴 판은 그 보정서의 접수번호가 꼭 있어야 한다
        CheckConstraint(
            "source_kind <> 'amendment' OR source_doc_number IS NOT NULL",
            name="ck_claim_versions_amendment_doc_number",
        ),
        # 보정서 판은 그 보정서 이력 줄에 꼭 이어진다. 접수번호는 저장 코드가 그 줄에서 채운다
        # (#120 리뷰 (가), #16). 두 번호가 같은지는 DB가 아니라 저장 코드 테스트가 본다
        CheckConstraint(
            "source_kind <> 'amendment' OR case_event_id IS NOT NULL",
            name="ck_claim_versions_amendment_event",
        ),
        UniqueConstraint("case_id", "version", name="uq_claim_versions_case_version"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("cv"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)  # 0 = 출원 때 판
    source_kind: Mapped[str] = mapped_column(Text)
    # 보정서면 접수번호, 공보면 공개·등록번호, 출원서면 비움
    source_doc_number: Mapped[str | None] = mapped_column(Text)
    case_event_id: Mapped[str | None] = mapped_column(ForeignKey("case_events.id"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    created_at: Mapped[datetime] = _created_at()


class Claim(Base):
    """판 안의 청구항 하나."""

    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("claim_version_id", "number", name="uq_claims_version_number"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("cl"))
    claim_version_id: Mapped[str] = mapped_column(ForeignKey("claim_versions.id"))
    number: Mapped[int] = mapped_column(Integer)
    is_independent: Mapped[bool] = mapped_column(Boolean)
    # 인용하는 앞 청구항 번호 (독립항이면 빈 목록)
    depends_on: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]")
    )
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class OA(Base):
    """OA 하나. 발송번호는 case_events.doc_number 한 곳에만 둔다 (case_event와 1:1)."""

    __tablename__ = "oas"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("oa"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    case_event_id: Mapped[str] = mapped_column(ForeignKey("case_events.id"), unique=True)
    # 심사 대상 청구항 판. 모르면 비우고 "확인되지 않음" (#16·#54가 채움)
    examined_claim_version_id: Mapped[str | None] = mapped_column(ForeignKey("claim_versions.id"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))  # OA 원문
    created_at: Mapped[datetime] = _created_at()
