"""노이즈 범위 검색기 감싸기 테스트 (이슈 #309). 지어낸 범위 파일과 가짜 검색기만 쓴다."""

import json
from datetime import date
from pathlib import Path

import pytest

from eval.f3.noise_searcher import NoiseScopedSearcher, load_doc_noise_scope
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow


class _Spy:
    """안쪽 검색기 자리. 받은 인자를 그대로 적어 둔다."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None, **kw):
        self.calls.append(
            {
                "query": query,
                "corpus": corpus,
                "mode": mode,
                "k": k,
                "doc_ids": doc_ids,
                "as_of": as_of,
                **kw,
            }
        )
        return "RESULT"


def _gold(row_id: str, docs: list[str]) -> GoldRow:
    return GoldRow(row_id=row_id, corpus="cite", query="q", doc_ids=docs, items=[])


def test_인용문헌_검색이_노이즈_문헌까지_넓어진다():
    spy = _Spy()
    s = NoiseScopedSearcher(spy, {"D1": ["N1", "N2"]})
    out = s.search("질의", "cite", "hybrid", 5, doc_ids=["D1"])
    assert out == "RESULT"
    assert spy.calls[0]["doc_ids"] == ["D1", "N1", "N2"]


def test_다른_인자는_그대로_넘긴다():
    spy = _Spy()
    s = NoiseScopedSearcher(spy, {"D1": ["N1"]})
    s.search(
        "질의", "cite", "bm25", 7, doc_ids=["D1"], as_of=date(2020, 1, 2), chunk_kinds=["claim"]
    )
    c = spy.calls[0]
    assert (c["query"], c["corpus"], c["mode"], c["k"]) == ("질의", "cite", "bm25", 7)
    assert c["as_of"] == date(2020, 1, 2)
    assert c["chunk_kinds"] == ["claim"]


def test_scope에_없는_문헌이나_doc_ids_None은_그대로():
    spy = _Spy()
    s = NoiseScopedSearcher(spy, {"D1": ["N1"]})
    s.search("q", "cite", "hybrid", 3, doc_ids=["D9"])
    s.search("q", "cite", "hybrid", 3)
    assert spy.calls[0]["doc_ids"] == ["D9"]
    assert spy.calls[1]["doc_ids"] is None


def test_노이즈에_인용문헌이_겹쳐도_한_번만_넣는다():
    spy = _Spy()
    s = NoiseScopedSearcher(spy, {"D1": ["D1", "N1", "N1"]})
    s.search("q", "cite", "hybrid", 3, doc_ids=["D1"])
    assert spy.calls[0]["doc_ids"] == ["D1", "N1"]


def _write(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "noise.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return p


def test_범위_파일에서_인용문헌별_노이즈_합집합을_만든다(tmp_path):
    # 같은 OA(A1)의 D1 줄 둘: 노이즈 합집합. 정답 문헌(D1, D2)은 노이즈에서 뺀다
    p = _write(
        tmp_path,
        [
            {"row_id": "A1:r1:c1:D1", "scope_doc_ids": ["D1", "N1", "N2"]},
            {"row_id": "A1:r1:c2:D1", "scope_doc_ids": ["D1", "N2", "N3"]},
            {"row_id": "A1:r1:c3:D2", "scope_doc_ids": ["D2", "D1", "N1"]},
        ],
    )
    gold = [
        _gold("A1:r1:c1:D1", ["D1"]),
        _gold("A1:r1:c2:D1", ["D1"]),
        _gold("A1:r1:c3:D2", ["D2", "D1"]),
    ]
    scope = load_doc_noise_scope(p, gold)
    assert scope["D1"] == ["N1", "N2", "N3"]
    assert scope["D2"] == ["N1"]


def test_범위_파일이_없으면_오류로_멈춘다(tmp_path):
    with pytest.raises(RetrievalEvalError):
        load_doc_noise_scope(tmp_path / "없음.jsonl", [_gold("A1:r1:c1:D1", ["D1"])])


def test_정답_줄이_범위_파일에_없으면_오류로_멈춘다(tmp_path):
    p = _write(tmp_path, [{"row_id": "A1:r1:c1:D1", "scope_doc_ids": ["D1", "N1"]}])
    with pytest.raises(RetrievalEvalError):
        load_doc_noise_scope(p, [_gold("A1:r1:c1:D1", ["D1"]), _gold("A1:r1:c2:D1", ["D1"])])
