"""노이즈 상위 오답 확인표 만들기 (이슈 #178 T4).

기대값은 #256 카드의 확인 방법에서 가져온다: 상위 k에 정답 위치가 없던 줄(CQ 후보) 중
노이즈 문헌 조각이 든 줄마다 가장 위 노이즈 조각 하나, 노이즈 종류(B는 같은 OA·다른 OA, C).
번호·글은 모두 지어낸 값이다.
"""

import csv
import json

from eval.retrieval.noise_review import build_review_rows, main


def cq(row_id: str, found: list[tuple[str, str]], query: str = "가짜 질의") -> dict:
    return {
        "row_id": row_id,
        "query": query,
        "items": [{"kind": "paragraph", "start": 5, "end": 5, "label": "[0005]"}],
        "found": [{"chunk_id": cid, "label": lab, "score": 1.0} for cid, lab in found],
    }


CHUNKS = {
    "v:KR1A:p5": (
        "KR1A",
        {"kind": "paragraph", "start": 5, "end": 5, "label": "[0005]"},
        "정답 글",
    ),
    "v:KR1A:p9": (
        "KR1A",
        {"kind": "paragraph", "start": 9, "end": 9, "label": "[0009]"},
        "정답 문헌 다른 글",
    ),
    "v:KR2A:p1": (
        "KR2A",
        {"kind": "paragraph", "start": 1, "end": 1, "label": "[0001]"},
        "같은 OA 노이즈 글",
    ),
    "v:KR3A:p2": (
        "KR3A",
        {"kind": "paragraph", "start": 2, "end": 2, "label": "[0002]"},
        "C 노이즈 글",
    ),
}
POOL = {"KR1A": {}, "KR2A": {}, "KR3A": {"only_oas": ["OA1"]}}
OA_DOCS = {"OA1": {"KR1A", "KR2A"}}


def test_줄마다_가장_위_노이즈_조각과_종류를_고른다():
    cqs = [
        cq(
            "OA1:r1:c1:KR1A",
            [("v:KR1A:p9", "[0009]"), ("v:KR2A:p1", "[0001]"), ("v:KR3A:p2", "[0002]")],
        ),
        cq("OA1:r2:c1:KR1A", [("v:KR3A:p2", "[0002]")]),
        cq("OA1:r3:c1:KR1A", [("v:KR1A:p9", "[0009]")]),  # 노이즈 없음: 빠진다
    ]
    rows = build_review_rows(cqs, CHUNKS, POOL, OA_DOCS)
    assert [r["줄"] for r in rows] == ["OA1:r1:c1:KR1A", "OA1:r2:c1:KR1A"]
    assert rows[0]["노이즈_순위"] == 2 and rows[0]["노이즈_종류"] == "B"
    assert rows[0]["B_출처"] == "같은 OA" and rows[0]["노이즈_글"] == "같은 OA 노이즈 글"
    assert rows[0]["상위_노이즈수"] == 2 and rows[0]["정답_글"].endswith("정답 글")
    assert rows[1]["노이즈_종류"] == "C" and rows[1]["B_출처"] == ""


def test_명령은_csv를_쓴다(tmp_path):
    cq_p = tmp_path / "cq.jsonl"
    cq_p.write_text(
        json.dumps(cq("OA1:r1:c1:KR1A", [("v:KR2A:p1", "[0001]")]), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ch_p = tmp_path / "chunks.jsonl"
    ch_p.write_text(
        "".join(
            json.dumps({"chunk_id": k, "doc_id": d, "location": loc, "text": t}, ensure_ascii=False)
            + "\n"
            for k, (d, loc, t) in CHUNKS.items()
        ),
        encoding="utf-8",
    )
    pool_p = tmp_path / "pool.yaml"
    pool_p.write_text(
        "docs:\n  KR1A: {app_no: P1, date: 2010-01-01}\n  KR2A: {app_no: P2, date: 2010-01-01}\n"
        "  KR3A: {app_no: P3, date: 2010-01-01, only_oas: [OA1]}\n"
        "oas:\n  OA1: {app_no: PA, priority_date: 2015-01-01}\n",
        encoding="utf-8",
    )
    gold_p = tmp_path / "gold.jsonl"
    gold_p.write_text(
        json.dumps({"row_id": "OA1:r1:c1:KR1A", "corpus": "cite", "doc_ids": ["KR1A", "KR2A"]})
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    argv = ["--cq", str(cq_p), "--chunks", str(ch_p), "--pool", str(pool_p)]
    argv += ["--gold", str(gold_p), "--out", str(out)]
    assert main(argv, ignored=lambda p: True) == 0  # tmp 경로는 git 밖으로 본다
    got = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert got[0]["B_출처"] == "같은 OA" and got[0]["판정"] == ""


def test_명령은_git에_들어갈_수_있는_경로에는_쓰지_않는다(tmp_path):
    out = tmp_path / "out.csv"
    argv = ["--cq", "x", "--chunks", "x", "--pool", "x", "--gold", "x", "--out", str(out)]
    assert main(argv, ignored=lambda p: False) == 1
    assert not out.exists()
