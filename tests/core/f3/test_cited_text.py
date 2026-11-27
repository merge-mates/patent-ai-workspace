"""인용문헌 원문 전체 보기 (11/27 시연 전 화면 점검): 색인 조각을 문헌 순서대로 잇는다."""

from patent_ai.core.f3_claim_compare.cited_text import cited_document
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IDX = "cite-idx-test"
NA = Edition(status="not_applicable")


def _chunk(cid, kind, loc_kind, label, text, start=None, claims=(), figures=(), doc="KR1A"):
    return Chunk(
        chunk_id=f"{IDX}:{doc}:{cid}",
        index_version=IDX,
        doc_id=doc,
        chunk_kind=kind,
        location=Location(
            kind=loc_kind, start=start, end=start, label=label,
            claims=list(claims), figures=list(figures),
        ),
        edition=NA,
        text=text,
    )  # fmt: skip


def _repo():
    rows = [
        _chunk("p0002", "body", "paragraph", "[0002]", "둘째 문단", start=2),
        _chunk("fig1", "figure_desc", "figure", "도 1", "도 1은 구성도", figures=[1]),
        _chunk("claim2", "claim", "claim", "청구항 2", "제1항에 있어서", claims=[2]),
        _chunk("abs", "abstract", "abstract", "요약", "요약 글"),
        _chunk("p0001", "body", "paragraph", "[0001]", "첫 문단", start=1),
        _chunk("claim1", "claim", "claim", "청구항 1", "장치", claims=[1]),
        _chunk("p0001", "body", "paragraph", "[0001]", "다른 문헌", start=1, doc="KR2A"),
    ]
    return InMemoryChunkRepository({"cite": rows})


def test_문헌_조각을_요약_청구항_본문_도면_순서로_잇는다():
    doc = cited_document(_repo(), IDX, "KR1A")
    assert [p.label for p in doc.parts] == [
        "요약",
        "청구항 1",
        "청구항 2",
        "[0001]",
        "[0002]",
        "도 1",
    ]
    assert doc.parts[3].text == "첫 문단" and doc.parts[3].chunk_id.endswith(":KR1A:p0001")


def test_색인에_없는_문헌은_None():
    assert cited_document(_repo(), IDX, "KR9A") is None
