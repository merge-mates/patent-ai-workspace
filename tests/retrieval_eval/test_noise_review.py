"""노이즈 상위 오답 확인표 만들기 (이슈 #178 T4).

기대값은 #256 카드의 확인 방법에서 가져온다: 상위 k에 정답 위치가 없던 줄(CQ 후보) 중
노이즈 문헌 조각이 든 줄마다 가장 위 노이즈 조각 하나, 노이즈 종류(B는 같은 OA·다른 OA, C).
번호·글은 모두 지어낸 값이다.
"""

import csv
import json

from eval.retrieval.noise_review import build_review_rows, main


def cq(
    row_id: str, found: list[tuple[str, str]], query: str = "가짜 질의", version: str = "idx-v1"
) -> dict:
    return {
        "row_id": row_id,
        "index_version": version,
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
    "v:KR4A:p3": (
        "KR4A",
        {"kind": "paragraph", "start": 3, "end": 3, "label": "[0003]"},
        "다른 OA 노이즈 글",
    ),
}
POOL = {"KR1A": {}, "KR2A": {}, "KR3A": {"only_oas": ["OA1"]}, "KR4A": {}}
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


def test_B_노이즈가_그_OA_인용문헌이_아니면_다른_OA다():
    # KR4A는 풀에 있지만(only_oas 없음 = B) OA1이 인용하지 않았다
    rows = build_review_rows(
        [cq("OA1:r1:c1:KR1A", [("v:KR4A:p3", "[0003]")])], CHUNKS, POOL, OA_DOCS
    )
    assert rows[0]["노이즈_종류"] == "B" and rows[0]["B_출처"] == "다른 OA"
    assert rows[0]["노이즈_문헌"] == "KR4A"


def _write_inputs(tmp_path, cqs: list[dict], chunks=CHUNKS, version: str = "idx-v1") -> list[str]:
    """명령 입력 파일 넷을 쓰고 --out 앞까지의 argv를 돌려준다."""
    cq_p = tmp_path / "cq.jsonl"
    cq_p.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cqs), encoding="utf-8"
    )
    ch_p = tmp_path / "chunks.jsonl"
    ch_p.write_text(
        "".join(
            json.dumps(
                {"chunk_id": k, "index_version": version, "doc_id": d, "location": loc, "text": t},
                ensure_ascii=False,
            )
            + "\n"
            for k, (d, loc, t) in chunks.items()
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
    return ["--cq", str(cq_p), "--chunks", str(ch_p), "--pool", str(pool_p), "--gold", str(gold_p)]


def test_명령은_csv를_쓴다(tmp_path):
    argv = _write_inputs(tmp_path, [cq("OA1:r1:c1:KR1A", [("v:KR2A:p1", "[0001]")])])
    out = tmp_path / "out.csv"
    assert main([*argv, "--out", str(out)], ignored=lambda p: True) == 0  # tmp는 git 밖으로 본다
    got = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert got[0]["B_출처"] == "같은 OA" and got[0]["판정"] == ""


def test_상위_조각이_조각_파일에_없으면_쓰지_않고_1로_끝낸다(tmp_path, capsys):
    # #256 리뷰 재현: KR2A 조각이 빠지면 가장 위 노이즈가 KR3A(C)로 바뀐 표가 써졌다
    chunks = {k: v for k, v in CHUNKS.items() if k != "v:KR2A:p1"}
    cqs = [cq("OA1:r1:c1:KR1A", [("v:KR2A:p1", "[0001]"), ("v:KR3A:p2", "[0002]")])]
    argv = _write_inputs(tmp_path, cqs, chunks=chunks)
    out = tmp_path / "out.csv"
    assert main([*argv, "--out", str(out)], ignored=lambda p: True) == 1
    assert not out.exists()
    assert "1개" in capsys.readouterr().err


def test_CQ와_조각_파일의_색인_판이_다르면_1로_끝낸다(tmp_path, capsys):
    cqs = [cq("OA1:r1:c1:KR1A", [("v:KR2A:p1", "[0001]")], version="idx-v1")]
    argv = _write_inputs(tmp_path, cqs, version="idx-v2")
    out = tmp_path / "out.csv"
    assert main([*argv, "--out", str(out)], ignored=lambda p: True) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "idx-v1" in err and "idx-v2" in err


def test_명령은_git에_들어갈_수_있는_경로에는_쓰지_않는다(tmp_path):
    out = tmp_path / "out.csv"
    argv = ["--cq", "x", "--chunks", "x", "--pool", "x", "--gold", "x", "--out", str(out)]
    assert main(argv, ignored=lambda p: False) == 1
    assert not out.exists()
