"""메모리 저장소 테스트 (색인 판·문헌·기준일 거르기). 기대값은 tasks.md m2-i1 task-3 기준."""

from datetime import date
from pathlib import Path

import pytest

from patent_ai.retrieval.repository import InMemoryChunkRepository

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
    got = repo.chunks("cite", "cite-idx-v1", doc_ids=["US9000001B2"])
    assert len(got) == 3
    assert {c.doc_id for c in got} == {"US9000001B2"}
    assert repo.count_chunks("cite", "cite-idx-v1", doc_ids=["US9000001B2"]) == 3


def test_as_of로_그날_시행_판본만(repo):
    old = repo.chunks("law", "law-idx-v1", as_of=date(2018, 6, 1))
    new = repo.chunks("law", "law-idx-v1", as_of=date(2024, 1, 1))  # 끝 없음 = 현행
    assert [c.edition.label for c in old] == ["가상법 구판"]
    assert [c.edition.label for c in new] == ["가상법 신판"]
    # 경계: 시작일·끝일 당일 포함
    assert len(repo.chunks("law", "law-idx-v1", as_of=date(2019, 12, 31))) == 1
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
