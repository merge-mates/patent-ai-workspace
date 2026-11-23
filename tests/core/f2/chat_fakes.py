"""대화 저장소 테스트가 같이 쓰는 값 (묶음·질문 만들기)."""

from datetime import UTC, date, datetime

from patent_ai.core.schemas.common import Evidence, Status
from patent_ai.core.schemas.legal_evidence import (
    LegalClaim,
    LegalEvidenceBundle,
    LegalQuestion,
    LegalSource,
    Review,
    summarize_bundle_status,
    summarize_claim_status,
)

OK = Status(value="confirmed", checked="원문 대조")
UNVERIFIED = Status(value="unverified", reason="edition_unknown")
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


def question(text="진보성 판단 기준은?") -> LegalQuestion:
    return LegalQuestion(
        text=text,
        source="user_question",
        as_of=None,
        as_of_source="none",
        source_kinds=["statute"],
        article_refs=[],
    )


def source(chunk_id: str | None, status=OK) -> LegalSource:
    return LegalSource(
        source_kind="statute",
        identifier="특허법 제29조 제2항",
        evidence=Evidence(
            document_id="law_patent",
            location="제29조 제2항",
            raw_text="발췌 문장",
            edition="2024-01-01 시행",
            checked_on=date(2026, 11, 23),
            chunk_id=chunk_id,
            index_version="law-idx-v3" if chunk_id else None,
        ),
        status=status,
    )


def bundle(bundle_id="lb_1", chunk_ids=("law_patent#12",), q=None, extra_sources=()):
    sources = [source(c) for c in chunk_ids] + list(extra_sources)
    claim_status = summarize_claim_status(sources)
    claim = LegalClaim(
        no=1,
        text="진보성은 선행기술로 쉽게 발명할 수 있으면 부정된다",
        sources=sources,
        status=claim_status,
        review=Review(verdict="supported", reason="근거가 뒷받침"),
    )
    return LegalEvidenceBundle(
        bundle_id=bundle_id,
        question=q or question(),
        checked_on=date(2026, 11, 23),
        claims=[claim],
        status=summarize_bundle_status([claim]),
    )
