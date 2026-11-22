"""task-2: 인용문헌 다시 찾기 도구 5개. 메모리 저장소 + 가짜 검색기, 네트워크·API 키 없음."""

import json

import pytest

from patent_ai.core.agents.tool_loop import GiveUp, RecheckToolFailed
from patent_ai.core.f3_claim_compare.recheck.tools import CiteToolbox, Submitted
from patent_ai.core.schemas.comparison import Judgment
from patent_ai.retrieval.fake import FakeSearcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "cite-idx-v2"


def para(doc: str, no: int, text: str, emb=None) -> Chunk:
    return Chunk(
        chunk_id=f"{IV}:{doc}:p{no:04d}",
        index_version=IV,
        doc_id=doc,
        chunk_kind="body",
        location=Location(kind="paragraph", start=no, end=no, label=f"[{no:04d}]"),
        edition=Edition(status="not_applicable"),
        text=text,
        embedding=emb or [1.0, 0.0],
    )


D1_1 = f"{IV}:D1:p0001"
D1_2 = f"{IV}:D1:p0002"
D1_3 = f"{IV}:D1:p0003"
D2_1 = f"{IV}:D2:p0001"


@pytest.fixture
def repo():
    return InMemoryChunkRepository(
        {
            "cite": [
                para("D1", 1, "제어부는 센서 신호를 받아 모터를 구동한다 " + "가" * 300),
                para("D1", 2, "컨트롤러가 온도 값을 읽는다"),
                para("D1", 3, "배터리 셀을 병렬로 연결한다"),
                para("D2", 1, "제어부 다른 문헌의 문단"),
            ]
        }
    )


def make_box(repo, *, exclude=frozenset(), embed=None, k_max=10, snippet=20):
    searcher = FakeSearcher(repo, {"index_version": IV}, embed=embed or (lambda q: [1.0, 0.0]))
    return CiteToolbox(
        searcher, repo, IV, "D1", "D1", set(exclude), k_max=k_max, snippet_chars=snippet
    )


def tool(box, name, judge="compare"):
    spec = {s.name: s for s in box.specs(judge)}[name]

    def call(**kw):
        return spec.run(spec.input_model.model_validate(kw))

    return call


def test_도구_다섯_개와_description은_prompts_파일에서(repo):
    box = make_box(repo)
    specs = box.specs("compare")
    assert [s.name for s in specs] == [
        "search_bm25",
        "search_vector",
        "open_paragraph",
        "submit_evidence",
        "give_up",
    ]
    assert all(s.description.strip() for s in specs)
    assert [s.terminal for s in specs] == [False, False, False, True, True]
    # judge에 따라 submit_evidence 설명과 입력 모양이 다르다
    agent = {s.name: s for s in box.specs("agent")}["submit_evidence"]
    compare = {s.name: s for s in specs}["submit_evidence"]
    assert agent.description != compare.description
    assert "items" in agent.api_definition()["input_schema"]["properties"]
    assert "paragraph_ids" in compare.api_definition()["input_schema"]["properties"]


def test_search_bm25_평소_앞_snippet만_담고_hits에_쌓는다(repo):
    box = make_box(repo, snippet=10)
    out = tool(box, "search_bm25")(query="제어부는 모터를", k=5)
    assert not out.is_error
    rows = json.loads(out.content)
    assert rows[0]["chunk_id"] == D1_1 and rows[0]["rank"] == 1
    assert rows[0]["location"] == "[0001]"
    assert rows[0]["snippet"] == "제어부는 센서 신호를"[:10]
    assert "note" not in rows[0]
    assert all(r["chunk_id"] != D2_1 for r in rows)  # 그 인용문헌 안에서만 찾는다
    assert box.hits == [D1_1] and out.result_ids == [D1_1]
    assert out.logged_input == {"query": "제어부는 모터를", "k": 5}


def test_search_vector는_vector_모드로_부른다(repo):
    box = make_box(repo)
    out = tool(box, "search_vector")(query="아무 말", k=2)
    rows = json.loads(out.content)
    assert [r["rank"] for r in rows] == [1, 2]
    assert len(box.hits) == 2


def test_1차에_본_조각은_빼지_않고_표시만_한다(repo):
    box = make_box(repo, exclude={D1_1})
    rows = json.loads(tool(box, "search_bm25")(query="제어부는 컨트롤러가", k=5).content)
    by_id = {r["chunk_id"]: r for r in rows}
    assert by_id[D1_1]["note"] == "(1차에 이미 봄)"
    assert "note" not in by_id[D1_2]
    assert D1_1 in box.hits


def test_hits는_순서를_지키고_같은_조각을_다시_쌓지_않는다(repo):
    box = make_box(repo)
    tool(box, "search_bm25")(query="컨트롤러가", k=5)
    tool(box, "search_bm25")(query="컨트롤러가 제어부는", k=5)
    assert box.hits == [D1_2, D1_1]


def test_검색_결과_0개는_오류가_아니라_안내(repo):
    box = make_box(repo)
    out = tool(box, "search_bm25")(query="없는낱말", k=5)
    assert out.is_error is False
    assert out.content == "결과 0개: 다른 말로 찾거나 give_up"
    assert box.hits == [] and out.result_ids == []


def test_검색_인자_범위_밖은_오류_결과(repo):
    box = make_box(repo, k_max=3)
    assert tool(box, "search_bm25")(query="a", k=4).is_error
    assert tool(box, "search_bm25")(query="a", k=0).is_error
    assert tool(box, "search_bm25")(query="가" * 201, k=1).is_error
    assert tool(box, "search_bm25")(query="  ", k=1).is_error


def test_검색_예외는_RecheckToolFailed(repo):
    def boom(q):
        raise RuntimeError("임베딩 서버 끊김")

    box = make_box(repo, embed=boom)
    with pytest.raises(RecheckToolFailed):
        tool(box, "search_vector")(query="a", k=1)


def test_open_paragraph_평소_전체_글과_앞뒤_ID(repo):
    box = make_box(repo)
    out = tool(box, "open_paragraph")(paragraph_id=D1_2)
    body = json.loads(out.content)
    assert body["text"] == "컨트롤러가 온도 값을 읽는다"
    assert body["prev"] == D1_1 and body["next"] == D1_3
    assert box.opened == [D1_2]
    first = json.loads(tool(box, "open_paragraph")(paragraph_id=D1_1).content)
    assert first["prev"] is None and first["next"] == D1_2
    assert out.logged_input == {"paragraph_id": D1_2}  # 글은 기록에 안 들어간다


def test_open_paragraph_없는_ID와_다른_문헌_ID는_오류_결과(repo):
    box = make_box(repo)
    for pid in (f"{IV}:D1:p9999", D2_1):
        out = tool(box, "open_paragraph")(paragraph_id=pid)
        assert out.is_error and pid in out.content and "chunk_id" in out.content
    assert box.opened == []


def test_검색에_나온_다른_문헌_조각은_열_수_있다(repo):
    # 둘째 점수(노이즈 범위)처럼 검색기가 doc_ids를 넓혀 주는 경우: 검색 결과에 나온 조각은 받는다
    class Widening:
        def __init__(self, inner):
            self.inner = inner

        def search(self, query, corpus, mode, k, doc_ids=None, **kw):
            return self.inner.search(query, corpus, mode, k, doc_ids=["D1", "D2"], **kw)

    inner = FakeSearcher(repo, {"index_version": IV}, embed=lambda q: [1.0, 0.0])
    box = CiteToolbox(Widening(inner), repo, IV, "D1", "D1", set(), k_max=10, snippet_chars=20)
    assert D2_1 in [
        r["chunk_id"] for r in json.loads(tool(box, "search_bm25")(query="다른", k=5).content)
    ]
    assert not tool(box, "open_paragraph")(paragraph_id=D2_1).is_error


def test_submit_compare_평소_연_문단이면_done(repo):
    box = make_box(repo)
    tool(box, "open_paragraph")(paragraph_id=D1_1)
    out = tool(box, "submit_evidence")(paragraph_ids=[D1_1], why="제어부 대응")
    assert out.is_error is False
    assert out.done == Submitted(paragraph_ids=[D1_1], why="제어부 대응")
    assert out.logged_input == {"paragraph_ids": [D1_1]}  # why·글 없음


def test_submit_안_연_문단은_오류_결과(repo):
    box = make_box(repo)
    out = tool(box, "submit_evidence")(paragraph_ids=[D1_1], why="x")
    assert out.is_error and out.done is None
    assert out.content.startswith(D1_1) and "열지 않은 문단" in out.content
    assert "open_paragraph" in out.content


def test_submit_없는_ID와_다른_문헌_ID는_오류_결과(repo):
    box = make_box(repo)
    for pid in (f"{IV}:D1:p9999", D2_1):
        out = tool(box, "submit_evidence")(paragraph_ids=[pid], why="x")
        assert out.is_error and out.done is None and pid in out.content


def test_submit_빈_목록과_여섯_개는_오류_결과(repo):
    box = make_box(repo)
    assert tool(box, "submit_evidence")(paragraph_ids=[], why="x").is_error
    assert tool(box, "submit_evidence")(paragraph_ids=[D1_1] * 6, why="x").is_error


def test_submit_why가_비면_오류_결과(repo):
    box = make_box(repo)
    tool(box, "open_paragraph")(paragraph_id=D1_1)
    assert tool(box, "submit_evidence")(paragraph_ids=[D1_1], why=" ").is_error


def test_submit_agent_항목_모양과_판정(repo):
    box = make_box(repo)
    tool(box, "open_paragraph")(paragraph_id=D1_2)
    call = tool(box, "submit_evidence", "agent")
    out = call(
        items=[{"paragraph_id": D1_2, "quote": "컨트롤러가 온도 값을"}],
        judgment="disclosed",
        why="컨트롤러가 제어부에 대응",
    )
    assert out.is_error is False
    sub = out.done
    assert sub.judgment is Judgment.DISCLOSED
    assert [(i.paragraph_id, i.quote) for i in sub.items] == [(D1_2, "컨트롤러가 온도 값을")]
    assert sub.paragraph_ids == [D1_2]
    # 기록에는 ID와 판정만, quote·글은 없다
    assert out.logged_input == {"paragraph_ids": [D1_2], "judgment": "disclosed"}
    assert "컨트롤러" not in json.dumps(out.logged_input, ensure_ascii=False)


def test_submit_agent_안_연_문단과_문단에_없는_quote는_오류_결과(repo):
    box = make_box(repo)
    call = tool(box, "submit_evidence", "agent")
    item = {"paragraph_id": D1_2, "quote": "컨트롤러가 온도 값을"}
    out = call(items=[item], judgment="disclosed", why="x")
    assert out.is_error and "열지 않은 문단" in out.content
    tool(box, "open_paragraph")(paragraph_id=D1_2)
    bad = call(
        items=[{"paragraph_id": D1_2, "quote": "문단에 없는 글자"}], judgment="unclear", why="x"
    )
    assert bad.is_error and "quote" in bad.content and bad.done is None


def test_submit_agent_판정_값은_Judgment_그대로(repo):
    box = make_box(repo)
    spec = {s.name: s for s in box.specs("agent")}["submit_evidence"]
    enum = spec.api_definition()["input_schema"]["$defs"]["Judgment"]["enum"]
    assert enum == ["disclosed", "difference_candidate", "unclear"]
    with pytest.raises(ValueError):
        spec.input_model.model_validate(
            {"items": [], "judgment": "partially_disclosed", "why": "x"}
        )


def test_give_up_평소와_글자수_상한(repo):
    box = make_box(repo)
    out = tool(box, "give_up")(reason="not_in_document", tried="제어부 검색")
    assert out.done == GiveUp(reason="not_in_document", tried="제어부 검색")
    assert out.logged_input == {"reason": "not_in_document"}
    over = tool(box, "give_up")(reason="other", tried="가" * 301)
    assert over.is_error and over.done is None


def test_정의에_길이_범위_개수_제약_키가_없다(repo):
    box = make_box(repo)
    banned = ("maxLength", "minLength", "minimum", "maximum", "maxItems", "minItems", "pattern")
    for judge in ("compare", "agent"):
        for spec in box.specs(judge):
            d = spec.api_definition()
            dumped = json.dumps(d, ensure_ascii=False)
            assert d["strict"] is True
            assert not [k for k in banned if f'"{k}"' in dumped], spec.name
