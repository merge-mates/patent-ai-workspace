"""검색 결과 스키마 테스트. 기대값은 design.md 3-2절 JSON 예시에서 가져온다."""

import copy

import pytest
from pydantic import ValidationError

from patent_ai.retrieval.schemas import Chunk, SearchHit, SearchResult

# design.md 3-2절 예시 그대로
EXAMPLE = {
    "corpus": "cite",
    "index_version": "cite-idx-v1",
    "mode": "bm25",
    "scope": {
        "doc_ids": ["KR1020190012345A"],
        "as_of": None,
        "k": 5,
        "chunk_kinds": None,
        "source_kinds": None,
        "decided_on_or_before": None,
    },
    "status": None,
    "status_reason": None,
    "skipped_unverified_edition": 0,
    "skipped_unknown_date": 0,
    "hits": [
        {
            "chunk_id": "cite-idx-v1:KR1020190012345A:p0023",
            "index_version": "cite-idx-v1",
            "doc_id": "KR1020190012345A",
            "chunk_kind": "body",
            "location": {
                "kind": "paragraph",
                "start": 23,
                "end": 23,
                "label": "[0023]",
                "figures": [],
                "claims": [],
            },
            "edition": {
                "status": "not_applicable",
                "effective_from": None,
                "effective_to": None,
                "label": None,
            },
            "text": "…",
            "source_kind": None,
            "decided_on": None,
            "speaker": None,
            "attrs": None,
            "score": 3.2,
            "rank": 1,
        }
    ],
}


def test_예시_JSON이_읽히고_같은_JSON으로_나온다():
    result = SearchResult.model_validate(EXAMPLE)
    assert result.hits[0].rank == 1
    assert result.model_dump(mode="json") == EXAMPLE


def test_빈_결과는_not_found_in_scope로_읽힌다():
    data = copy.deepcopy(EXAMPLE)
    data["hits"] = []
    data["status"] = "not_found_in_scope"
    result = SearchResult.model_validate(data)
    assert result.hits == []
    assert result.status == "not_found_in_scope"


def test_빈_결과_unverified는_body_missing_이유를_받는다():
    data = copy.deepcopy(EXAMPLE)
    data["hits"] = []
    data["status"] = "unverified"
    data["status_reason"] = "body_missing"
    assert SearchResult.model_validate(data).status_reason == "body_missing"


def test_edition_status가_정해진_값_밖이면_오류():
    data = copy.deepcopy(EXAMPLE)
    data["hits"][0]["edition"]["status"] = "maybe"
    with pytest.raises(ValidationError):
        SearchResult.model_validate(data)


@pytest.mark.parametrize("bad", ["confirmed", "conflict"])
def test_검색_결과는_confirmed_conflict_상태를_못_가진다(bad):
    data = copy.deepcopy(EXAMPLE)
    data["hits"] = []
    data["status"] = bad
    with pytest.raises(ValidationError):
        SearchResult.model_validate(data)


def test_hits가_있는데_status가_있으면_오류():
    data = copy.deepcopy(EXAMPLE)
    data["status"] = "not_found_in_scope"
    with pytest.raises(ValidationError):
        SearchResult.model_validate(data)


def test_hits가_비었는데_status가_없으면_오류():
    # 빈 결과를 상태 없이 두면 "없음"과 "못 찾음"이 구분 안 된다
    data = copy.deepcopy(EXAMPLE)
    data["hits"] = []
    with pytest.raises(ValidationError):
        SearchResult.model_validate(data)


def test_status가_unverified인데_status_reason이_없으면_오류():
    data = copy.deepcopy(EXAMPLE)
    data["hits"] = []
    data["status"] = "unverified"
    with pytest.raises(ValidationError):
        SearchResult.model_validate(data)


def test_status_reason은_status가_unverified일_때만_올_수_있다():
    data = copy.deepcopy(EXAMPLE)
    data["hits"] = []
    data["status"] = "not_found_in_scope"
    data["status_reason"] = "body_missing"
    with pytest.raises(ValidationError):
        SearchResult.model_validate(data)


def test_SearchHit은_Chunk의_칸에_score와_rank를_더한_것():
    hit = SearchResult.model_validate(EXAMPLE).hits[0]
    assert isinstance(hit, SearchHit) and isinstance(hit, Chunk)


def test_SearchHit_JSON에는_embedding이_나오지_않는다():
    # embedding을 실제로 넣어야 exclude=True가 지켜지는지 잰다
    hit = SearchResult.model_validate(EXAMPLE).hits[0]
    with_embedding = SearchHit(**{**hit.model_dump(), "embedding": [0.1]})
    assert with_embedding.embedding == [0.1]
    assert "embedding" not in with_embedding.model_dump(mode="json")


def test_Chunk에서_SearchHit으로_변환이_읽힌다():
    chunk_data = {k: v for k, v in EXAMPLE["hits"][0].items() if k not in ("score", "rank")}
    chunk = Chunk.model_validate(chunk_data)
    assert chunk.embedding is None
    hit = SearchHit(**chunk.model_dump(), score=3.2, rank=1)
    assert hit.chunk_id == chunk.chunk_id and hit.rank == 1


# ---- 새 칸 (이슈 #24 24a) ----
def _chunk_json(**over):
    d = {
        "chunk_id": "law-idx-v3:판례_1:요지",
        "index_version": "law-idx-v3",
        "doc_id": "판례_1",
        "chunk_kind": "judgment_summary",
        "location": {"kind": "paragraph", "label": "요지"},
        "edition": {"status": "not_applicable"},
        "text": "가짜 요지",
    }
    d.update(over)
    return d


def test_judgment_summary와_새_칸_넷을_읽는다():
    c = Chunk.model_validate(
        _chunk_json(
            source_kind="precedent",
            decided_on="2021-05-13",
            speaker="court",
            attrs={"court": "대법원"},
        )
    )
    assert c.chunk_kind == "judgment_summary"
    assert (c.source_kind, c.speaker, c.attrs) == ("precedent", "court", {"court": "대법원"})
    assert c.decided_on.isoformat() == "2021-05-13"


def test_새_칸은_모두_선택이라_옛_JSON도_읽힌다():
    c = Chunk.model_validate(_chunk_json(chunk_kind="article", edition={"status": "confirmed"}))
    assert (c.source_kind, c.decided_on, c.speaker, c.attrs) == (None, None, None, None)


@pytest.mark.parametrize("field,bad", [("source_kind", "statut"), ("speaker", "judge")])
def test_새_칸이_정해진_값_밖이면_오류(field, bad):
    with pytest.raises(ValidationError):
        Chunk.model_validate(_chunk_json(**{field: bad}))
