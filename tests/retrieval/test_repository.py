"""메모리 저장소 테스트 (색인 판·문헌·기준일 거르기). 기대값은 tasks.md m2-i1 task-3 기준."""

from datetime import date
from pathlib import Path

import pytest

from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk

FIX = Path(__file__).parent.parent / "fixtures" / "retrieval"
CITE = FIX / "chunks_cite.jsonl"
LAW = FIX / "chunks_law.jsonl"


@pytest.fixture
def repo():
    return InMemoryChunkRepository.merge(
        InMemoryChunkRepository.from_jsonl("cite", CITE),
        InMemoryChunkRepository.from_jsonl("law", LAW),
    )


def test_색인_판으로_거른다(repo):
    assert len(repo.chunks("cite", "cite-idx-v1")) == 16
    assert repo.has_index_version("cite", "cite-idx-v1")
    assert not repo.has_index_version("cite", "cite-idx-v2")
    # 말뭉치가 다르면 같은 판 이름도 없음
    assert not repo.has_index_version("law", "cite-idx-v1")


def test_doc_ids로_한_공보만(repo):
    got = repo.chunks("cite", "cite-idx-v1", doc_ids=["US0000001B2"])
    assert len(got) == 3
    assert {c.doc_id for c in got} == {"US0000001B2"}
    assert repo.count_chunks("cite", "cite-idx-v1", doc_ids=["US0000001B2"]) == 3


def test_as_of로_그날_시행_판본만(repo):
    old = repo.chunks("law", "law-idx-v1", as_of=date(2018, 6, 1))
    new = repo.chunks("law", "law-idx-v1", as_of=date(2024, 1, 1))  # 끝 없음 = 현행
    assert [c.edition.label for c in old] == ["가상법 구판"]
    assert [c.edition.label for c in new] == ["가상법 신판"]
    # 경계: 시작일·끝일 당일 포함
    boundary = repo.chunks("law", "law-idx-v1", as_of=date(2019, 12, 31))
    assert [c.edition.label for c in boundary] == ["가상법 구판"]
    assert (
        repo.chunks("law", "law-idx-v1", as_of=date(2020, 1, 1))[0].edition.label == "가상법 신판"
    )
    # 어느 판도 시행 전이면 빈 목록
    assert repo.chunks("law", "law-idx-v1", as_of=date(2000, 1, 1)) == []


def test_as_of_없으면_unverified도_포함(repo):
    assert len(repo.chunks("law", "law-idx-v1")) == 3


def test_as_of_검색에서_unverified는_빠지고_셈(repo):
    got = repo.chunks("law", "law-idx-v1", as_of=date(2024, 1, 1))
    assert all(c.edition.status != "unverified" for c in got)
    assert repo.count_unverified_edition("law", "law-idx-v1") == 1
    assert repo.count_unverified_edition("cite", "cite-idx-v1") == 0


def test_인용문헌은_as_of여도_거르지_않음(repo):
    assert len(repo.chunks("cite", "cite-idx-v1", as_of=date(2018, 1, 1))) == 16


def test_없는_공보는_빈_목록과_0(repo):
    assert repo.chunks("cite", "cite-idx-v1", doc_ids=["KR0000000000A"]) == []
    assert repo.count_chunks("cite", "cite-idx-v1", doc_ids=["KR0000000000A"]) == 0


def test_빈_doc_ids는_오류(repo):
    with pytest.raises(ValueError):
        repo.chunks("cite", "cite-idx-v1", doc_ids=[])
    with pytest.raises(ValueError):
        repo.count_chunks("cite", "cite-idx-v1", doc_ids=[])
    with pytest.raises(ValueError):
        repo.count_unverified_edition("law", "law-idx-v1", doc_ids=[])


def test_말뭉치와_색인_판_앞말이_다르면_오류():
    # cite 파일을 law 표로 읽으면 앞말이 안 맞는다
    with pytest.raises(ValueError, match="cite-idx-v1"):
        InMemoryChunkRepository.from_jsonl("law", CITE)


def test_chunk_id가_겹치면_오류():
    with pytest.raises(ValueError, match="chunk_id"):
        InMemoryChunkRepository.from_jsonl("cite", CITE, CITE)


def _law_chunk(chunk_id, edition):
    return Chunk(
        chunk_id=chunk_id,
        index_version="law-idx-v1",
        doc_id="가상법",
        chunk_kind="article",
        location={"kind": "article", "label": "제1조"},
        edition=edition,
        text="가짜 조문",
    )


def test_시작일_없는_confirmed는_as_of에서_빠지고_판본_모름으로_센다():
    odd = _law_chunk("law-idx-v1:가상법:제1조", {"status": "confirmed"})
    repo = InMemoryChunkRepository({"law": [odd]})
    # as_of 검색에서 빠지는 조각은 반드시 셈에 잡혀야 한다 (조용히 사라지면 안 된다)
    assert repo.chunks("law", "law-idx-v1", as_of=date(2024, 1, 1)) == []
    assert repo.count_unverified_edition("law", "law-idx-v1") == 1


def test_판본_모름_셈에_doc_ids를_넘기면_그_문헌만_센다(repo):
    assert repo.count_unverified_edition("law", "law-idx-v1", doc_ids=["가상심사기준"]) == 1
    assert repo.count_unverified_edition("law", "law-idx-v1", doc_ids=["가상법"]) == 0


def _write(tmp_path, chunk):
    path = tmp_path / "x.jsonl"
    path.write_text(chunk.model_dump_json() + "\n", encoding="utf-8")
    return path


def test_law에_not_applicable_조각이_오면_파일과_줄을_담아_오류(tmp_path):
    bad = _law_chunk("law-idx-v1:가상법:제1조", {"status": "not_applicable"})
    with pytest.raises(ValueError, match=r"x\.jsonl:1"):
        InMemoryChunkRepository.from_jsonl("law", _write(tmp_path, bad))


def test_cite에_not_applicable이_아닌_조각이_오면_파일과_줄을_담아_오류(tmp_path):
    bad = _law_chunk("cite-idx-v1:D1:1", {"status": "unverified"}).model_copy(
        update={"index_version": "cite-idx-v1"}
    )
    with pytest.raises(ValueError, match=r"x\.jsonl:1"):
        InMemoryChunkRepository.from_jsonl("cite", _write(tmp_path, bad))
