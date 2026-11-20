"""F3 테스트용 지어낸 입력 만들기 (OA 정리 결과, 나눈 청구항, 색인 조각). 진짜 사건 글자 없음."""

from patent_ai.core.f3_claim_compare.elements import ClaimElement, SplitClaim, element_location
from patent_ai.core.schemas.common import (
    ExtractedValue,
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.oa_result import (
    Citation,
    ClaimRow,
    ExaminerHints,
    NoticeKind,
    OAResult,
    build_oa_result,
)
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "cite-idx-v2"
OK = Status(value=StatusValue.CONFIRMED, checked="테스트")


def bad(reason: UnverifiedReason = UnverifiedReason.NOT_EXTRACTED) -> Status:
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def ev(value, raw: str = "원문 글자", page: int = 1) -> ExtractedValue:
    """확인된 값 하나."""
    return ExtractedValue(value=value, raw_text=raw, page=page, status=OK)


def citation(label: str, number: str | None, country: str | None = "KR", paragraphs=None):
    """인용문헌 하나. number=None이면 번호를 못 읽은 것, country=None이면 나라를 못 정한 것."""
    supported = country in ("KR", "US")
    number_value = (
        ev(number, raw=number)
        if number is not None
        else ExtractedValue(
            value=None, raw_text="어느 학회 논문", page=1, status=bad(UnverifiedReason.AMBIGUOUS)
        )
    )
    country_value = (
        ev(country, raw=country)
        if country is not None
        else ExtractedValue(value=None, status=bad(UnverifiedReason.AMBIGUOUS))
    )
    return Citation(
        label=label,
        number=number_value,
        country=country_value,
        country_supported=supported,
        cited_paragraphs=ev(paragraphs) if paragraphs else ExtractedValue(value=None, status=bad()),
        flags=[] if supported else [Flag.NEEDS_HUMAN_REVIEW],
    )


def rejection(no: int, article: str, claims: list[int] | None, citations=(), reasoning="결합 논리"):
    """거절이유 하나 (build_oa_result에 넘길 칸 dict). claims=None이면 대상 청구항을 못 읽은 것."""
    supported = article in ("29-1-1", "29-1-2", "29-1-1|29-1-2", "29-2", "42-4-2")
    return {
        "no": no,
        "article": ev(article, raw=article),
        "supported": supported,
        "claims": ev(claims) if claims is not None else ExtractedValue(value=None, status=bad()),
        "citations": list(citations),
        "examiner_reasoning": ev(reasoning, raw=reasoning),
        "flags": [] if supported else [Flag.NEEDS_HUMAN_REVIEW],
    }


def claim_row(claim: int, rejection_no: int, citations=(), locations=None, same_as=()) -> ClaimRow:
    return ClaimRow(
        claim=claim,
        rejection=rejection_no,
        citations=list(citations),
        locations=locations or {},
        same_as=list(same_as),
        raw_text="이 줄 판단 원문",
        page=2,
        status=OK,
    )


def oa(rejections: list[dict], claim_rows=()) -> OAResult:
    return build_oa_result(
        document_id="d_oa",
        oa_id="oa_1",
        application_number=ev("1020990000001"),
        dispatch_number=ev("952099000000001"),
        notice_date=ev(None, raw="2099.01.26."),
        response_due=ev(None, raw="2099.03.26."),
        notice_kind=ExtractedValue[NoticeKind](value=NoticeKind.INITIAL, status=OK),
        examined_claims=ev([1, 2, 3, 4, 5]),
        examiner_hints=ExaminerHints(allowable_claims=ev([]), amendment_note=ev(None)),
        rejections=rejections,
        claim_rows=list(claim_rows),
    )


def split(claim: int, elements: list[str], depends_on: list[int] | None = ()) -> SplitClaim:
    """나눈 청구항 하나. depends_on=None이면 인용 관계를 확인하지 못한 것."""
    made, cursor = [], 0
    for no, text in enumerate(elements, start=1):
        made.append(
            ClaimElement(
                claim=claim,
                no=no,
                text=text,
                element_location=element_location(claim, no),
                start=cursor,
                end=cursor + len(text),
                status=OK,
            )
        )
        cursor += len(text) + 2
    depends_status = OK if depends_on is not None else bad()
    return SplitClaim(
        claim=claim,
        elements=made,
        depends_on=list(depends_on) if depends_on is not None else None,
        depends_on_quote="제N항에 있어서" if depends_on else None,
        depends_on_status=depends_status,
        status=depends_status,
    )


def chunk(doc: str, key: str, text: str, emb: list[float], **location) -> Chunk:
    """색인 조각 하나. location 예: kind="paragraph", start=23, end=23, label="[0023]"."""
    kind = {"paragraph": "body", "claim": "claim", "abstract": "abstract", "figure": "figure_desc"}
    return Chunk(
        chunk_id=f"{IV}:{doc}:{key}",
        index_version=IV,
        doc_id=doc,
        chunk_kind=kind[location["kind"]],
        location=Location(**location),
        edition=Edition(status="not_applicable"),
        text=text,
        embedding=emb,
    )


def paragraph(doc: str, no: int, text: str, emb: list[float], figures=()) -> Chunk:
    label = f"[{no:04d}]"
    return chunk(
        doc,
        f"p{no:04d}",
        text,
        emb,
        kind="paragraph",
        start=no,
        end=no,
        label=label,
        figures=list(figures),
    )
