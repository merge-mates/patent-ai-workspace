"""청킹 (요구 1·2·7). 줄 목록만 쓰고 PDF는 안 읽는다. 글자는 모두 지어낸 것."""

import json
from pathlib import Path

from patent_ai.retrieval.cite_index import PageText
from patent_ai.retrieval.cite_index.chunker import chunk_document, parse_figures

FIX = Path(__file__).parent.parent / "fixtures" / "cite_search" / "kr_pages.json"
IV = "cite-idx-v1"
DOC = "KR1020200000001A"


def _pages(raw=None):
    raw = raw or json.loads(FIX.read_text(encoding="utf-8"))
    return [PageText(page=p["page"], lines=p["lines"]) for p in raw]


def _by_key(chunks):
    return {c.chunk_id.split(":", 2)[2]: c for c in chunks}


def test_조각_키와_종류():
    chunks, warns = chunk_document(DOC, _pages(), IV)
    keys = [c.chunk_id.split(":", 2)[2] for c in chunks]
    assert keys == [
        "abs", "claim1", "claim2", "p0001", "p0002", "p0003",
        "fig1", "fig3a", "fig3b", "p0004",
    ]  # fmt: skip
    assert warns == []
    c = _by_key(chunks)
    assert c["p0002"].chunk_id == f"{IV}:{DOC}:p0002"
    assert c["p0002"].index_version == IV and c["p0002"].doc_id == DOC
    assert c["p0002"].chunk_kind == "body"
    assert c["claim1"].chunk_kind == "claim"
    assert c["abs"].chunk_kind == "abstract"
    assert c["fig3a"].chunk_kind == "figure_desc"
    assert all(x.edition.status == "not_applicable" for x in chunks)
    assert all(x.text.strip() for x in chunks)


def test_위치():
    c = _by_key(chunk_document(DOC, _pages(), IV)[0])
    loc = c["p0002"].location
    assert (loc.kind, loc.start, loc.end, loc.label) == ("paragraph", 2, 2, "[0002]")
    assert c["p0003"].location.label == "【0003】"  # 원문 표기 그대로
    assert c["claim2"].location.kind == "claim" and c["claim2"].location.claims == [2]
    assert c["abs"].location.kind == "abstract"
    assert c["abs"].location.figures == [2]  # 대표도
    assert c["fig3a"].location.kind == "figure" and c["fig3a"].location.figures == [3]


def test_글자_이어붙임():
    c = _by_key(chunk_document(DOC, _pages(), IV)[0])
    # 줄바꿈은 공백으로, 쪽을 넘는 문단은 이어 붙는다
    assert c["claim1"].text == "지어낸 장치 구성요소 가 를 포함하는 장치"
    assert (
        c["p0002"].text
        == "둘째 문단은 도 3 내지 도 5에 서 보인다. 온도 300℃ 에서 쓴다. 쪽을 넘는 이어진 줄"
    )
    assert c["abs"].text == "지어낸 요약 문장 하나 이어지는 요약 둘째 줄"


def test_본문_도면_번호():
    c = _by_key(chunk_document(DOC, _pages(), IV)[0])
    assert c["p0002"].location.figures == [3, 4, 5]
    assert c["p0001"].location.figures == []


def test_도면_번호_읽기():
    assert parse_figures("도 3 내지 도 5에서") == [3, 4, 5]
    assert parse_figures("도 3-5") == [3, 4, 5]
    assert parse_figures("도 3 및 4") == [3, 4]
    assert parse_figures("도 3a와 도면 7") == [3, 7]
    assert parse_figures("온도 300에서") == []
    assert parse_figures("도 3.5 도 4%") == []
    assert parse_figures("없음") == []


def test_도면설명이_문단_안에_있으면_둘_다():
    pages = [
        PageText(
            page=1,
            lines=[
                "[0001] 앞 문단",
                "도면의 간단한 설명",
                "[0002] 도 1은 가 도면",
                "도 2는 나 도면",
                "[0003] 발명을 실시하기 위한 구체적인 설명 문단",
            ],
        )
    ]
    chunks, _ = chunk_document(DOC, pages, IV)
    keys = [c.chunk_id.split(":", 2)[2] for c in chunks]
    assert keys == ["p0001", "p0002", "fig1", "fig2", "p0003"]
    c = _by_key(chunks)
    assert c["fig1"].text == "도 1은 가 도면"
    assert c["p0002"].text == "도 1은 가 도면 도 2는 나 도면"
    assert c["fig1"].location.kind == "figure"


def test_도면_쪽은_조각이_아님():
    chunks, _ = chunk_document(DOC, _pages(), IV)
    assert not any("도면1" in c.text for c in chunks)
    assert chunks[-1].chunk_id.endswith(":p0004")
    assert chunks[-1].text == "실시 문단"


def test_같은_입력_두_번_같음():
    a, _ = chunk_document(DOC, _pages(), IV)
    b, _ = chunk_document(DOC, _pages(), IV)
    assert [x.model_dump() for x in a] == [x.model_dump() for x in b]


def test_모든_조각_위치_안_빔():
    chunks, _ = chunk_document(DOC, _pages(), IV)
    for c in chunks:
        assert c.location.label
        if c.location.kind == "paragraph":
            assert c.location.start is not None


def test_논문은_쪽마다_한_조각():
    pages = [
        PageText(page=1, lines=["first page", "more"]),
        PageText(page=2, lines=[]),
        PageText(page=3, lines=["third"]),
    ]
    chunks, warns = chunk_document("NPL-paper-2020", pages, IV)
    assert [c.chunk_id for c in chunks] == [
        f"{IV}:NPL-paper-2020:pg1",
        f"{IV}:NPL-paper-2020:pg3",
    ]
    assert chunks[0].chunk_kind == "body"
    assert (chunks[0].location.kind, chunks[0].location.start, chunks[0].location.end) == (
        "page", 1, 1,
    )  # fmt: skip
    assert chunks[0].text == "first page more"
    assert warns  # 글자 없는 쪽 경고


def test_식별번호_없는_공보는_본문_안_만들고_나머지는_만듦():
    pages = [
        PageText(page=1, lines=["(57) 요 약", "요약 글", "특허청구의 범위", "청구항 1", "가 나", "명 세 서", "번호 없는 본문 줄"]),
    ]  # fmt: skip
    chunks, warns = chunk_document(DOC, pages, IV)
    assert [c.chunk_id.split(":", 2)[2] for c in chunks] == ["abs", "claim1"]
    assert "식별번호 없음: 본문 조각 안 만듦" in warns
    assert not any("번호 없는 본문" in c.text for c in chunks)


def test_전부_없으면_조각_0개와_경고():
    chunks, warns = chunk_document(DOC, [PageText(page=1, lines=["아무 글"])], IV)
    assert chunks == []
    assert "식별번호 없음: 본문 조각 안 만듦" in warns
    assert len(warns) >= 2


def test_지원_안_하는_나라():
    chunks, warns = chunk_document("US1234567B2", _pages(), IV)
    assert chunks == []
    assert any("지원 안 함" in w for w in warns)


def test_같은_식별번호_두_번이면_뒤를_버림():
    pages = [PageText(page=1, lines=["[0001] 앞것", "[0002] 중간", "[0001] 뒤것"])]
    chunks, warns = chunk_document(DOC, pages, IV)
    assert [c.chunk_id.split(":", 2)[2] for c in chunks] == ["p0001", "p0002"]
    assert chunks[0].text == "앞것"
    assert any("p0001" in w for w in warns)


def test_같은_도면_키_두_번이면_앞만_남김():
    pages = [PageText(page=1, lines=["도면의 간단한 설명", "도 1은 앞", "도 1은 뒤"])]
    chunks, warns = chunk_document(DOC, pages, IV)
    assert [c.text for c in chunks] == ["도 1은 앞"]
    assert any("fig1" in w for w in warns)


def test_같은_청구항_번호는_머리로_안_봄():
    # 번호가 늘지 않는 "청구항 1" 한 줄은 앞 청구항의 글자다
    pages = [
        PageText(page=1, lines=["특허청구의 범위", "청구항 1", "가", "청구항 2", "청구항 1", "나"])
    ]
    chunks, _ = chunk_document(DOC, pages, IV)
    assert [c.chunk_id.split(":", 2)[2] for c in chunks] == ["claim1", "claim2"]
    assert chunks[1].text == "청구항 1 나"


def test_청구항_점과_띄어쓴_제목():
    pages = [PageText(page=1, lines=["청 구 범 위", "청구항 20.", "가 나", "청구항 21.", "다"])]
    chunks, _ = chunk_document(DOC, pages, IV)
    assert [c.chunk_id.split(":", 2)[2] for c in chunks] == ["claim20", "claim21"]
