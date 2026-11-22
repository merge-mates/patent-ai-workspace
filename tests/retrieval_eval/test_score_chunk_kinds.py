"""채점기 검색 범위의 chunk_kinds (tasks.md m3-i1-24 task-a4).

기대값은 tasks.md task-a4 "테스트할 경우"에서 가져왔다: law 줄에 칸이 없으면 [article]로 찾고
(판례 조각이 더 잘 맞아도 안 걸림), 무작위 기준선 범위 N = 조문 조각 수, cite 줄은 그대로.
"""

import json
from pathlib import Path

import pytest

from eval.retrieval.config import load_config
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow, load_gold
from eval.retrieval.score import score
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk

IV = "law-idx-v3"
QUERY = "신규성 판단"
ROW_ID = "10-2020-0000301:r1"


def _law_chunk(name, kind, source_kind, edition, text, label):
    return Chunk(
        chunk_id=f"{IV}:{name}",
        index_version=IV,
        doc_id=name,
        chunk_kind=kind,
        location={"kind": "article", "label": label},
        edition=edition,
        text=text,
        source_kind=source_kind,
    )


def _repo():
    confirmed = {"status": "confirmed", "effective_from": "2020-01-01"}
    return InMemoryChunkRepository(
        {
            "law": [
                _law_chunk("특허법", "article", "statute", confirmed, "신규성", "제29조"),
                # 질의와 더 잘 맞는 판례 조각 (조문 줄 범위에 섞이면 안 된다)
                _law_chunk(
                    "판례1",
                    "judgment",
                    "precedent",
                    {"status": "not_applicable"},
                    "신규성 판단 신규성 판단",
                    "판시",
                ),
            ]
        }
    )


def _gold_line(**extra):
    row = {
        "row_id": ROW_ID,
        "corpus": "law",
        "query": QUERY,
        "doc_ids": None,
        "as_of": "2020-05-04",
        "items": [
            {
                "kind": "article",
                "label": "제29조",
                "gold_edition": {"status": "confirmed", "effective_from": "2020-01-01"},
            }
        ],
        "exclude": None,
        **extra,
    }
    return json.dumps(row, ensure_ascii=False) + "\n"


def _run(tmp_path: Path, line: str):
    root = tmp_path / "goldsets"
    (root / "tune" / "retrieval").mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    (root / "tune" / "retrieval" / "gold_kinds.jsonl").write_text(line, encoding="utf-8")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "experiment: m3-i1-kinds-test",
                "goldset: tune",
                "goldset_version: 1",
                "corpus: law",
                f"index_version: {IV}",
                "mode: bm25",
                "impl: fake",
                "k: [1, 3]",
                "gold: retrieval/gold_kinds.jsonl",
                "settings:",
                f"  index_version: {IV}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return score(
        load_config(cfg_path),
        _repo(),
        root,
        "abc",
        scores_dir=tmp_path / "out",
        cq_dir=tmp_path / "cq",
    )


def test_칸이_없는_law_줄은_조문만_찾고_범위_N도_조문_수(tmp_path):
    report = _run(tmp_path, _gold_line())
    row = report.rows[0]
    assert [h.chunk_kind for h in row.hits] == ["article"]  # 판례가 더 잘 맞아도 안 걸린다
    assert row.n_scope == 1


def test_칸에_judgment를_적으면_판례도_범위에_든다(tmp_path):
    report = _run(tmp_path, _gold_line(chunk_kinds=["article", "judgment"]))
    row = report.rows[0]
    assert row.n_scope == 2
    assert [h.chunk_kind for h in row.hits] == ["judgment", "article"]  # 더 잘 맞는 판례가 먼저


def test_gold_칸_읽기(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text(_gold_line() + _gold_line(row_id="10-2020-0000302:r1", chunk_kinds=["guideline"]))
    rows = load_gold(p)
    assert rows[0].chunk_kinds is None
    assert rows[0].search_chunk_kinds() == ["article"]  # law 기본
    assert rows[1].search_chunk_kinds() == ["guideline"]


def test_cite_줄은_기본으로_거르지_않는다():
    row = GoldRow(
        row_id="10-2020-0000303:r1:c1:KR1A",
        corpus="cite",
        query="q",
        doc_ids=["KR1A"],
        items=[{"kind": "paragraph", "start": 1, "end": 1, "label": "[0001]"}],
    )
    assert row.search_chunk_kinds() is None


def test_빈_chunk_kinds와_모르는_값은_오류(tmp_path):
    for bad in ([], ["없는종류"]):
        p = tmp_path / "bad.jsonl"
        p.write_text(_gold_line(chunk_kinds=bad))
        with pytest.raises(RetrievalEvalError):
            load_gold(p)
