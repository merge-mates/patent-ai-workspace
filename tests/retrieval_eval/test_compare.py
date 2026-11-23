"""비교 도구 compare (design.md 7-5, requirements 10). 지어낸 줄별 파일로 손 계산과 맞춘다."""

import json

import pytest

from eval.retrieval.compare import CompareError, RowHit, compare, group_of, main, render


def rows(spec):
    """spec: [(row_id, doc_id, rank)]"""
    return [RowHit(r, [d], k, 10) for r, d, k in spec]


# KR 2줄 + NPL 1줄. 순위: 줄별로 방식마다 다름
BM25 = rows([("a", "KR1", 1), ("b", "KR2", None), ("c", "NPL-x-1", 12)])
VEC = rows([("a", "KR1", 4), ("b", "KR2", 2), ("c", "NPL-x-1", 3)])
HYB = rows([("a", "KR1", 1), ("b", "KR2", 3), ("c", "NPL-x-1", None)])


def test_묶음별_Hit가_손_계산과_같다():
    t = compare({"bm25": BM25, "vector": VEC, "hybrid": HYB}, k=10)
    assert t.n == {"전체": 3, "한국 공보": 2, "논문": 1, "미국 공보": 0, "그 밖": 0}
    # bm25: a=1, b=없음, c=12 -> Hit@1 전체 1/3, Hit@10 전체 1/3 (c는 12위라 밖)
    assert t.hit["bm25"]["전체"][1] == pytest.approx(1 / 3)
    assert t.hit["bm25"]["전체"][10] == pytest.approx(1 / 3)
    assert t.hit["bm25"]["한국 공보"][1] == pytest.approx(1 / 2)
    assert t.hit["bm25"]["논문"][10] == 0
    # vector: 순위 4, 2, 3 -> Hit@3 전체 2/3, Hit@5 전체 1
    assert t.hit["vector"]["전체"][3] == pytest.approx(2 / 3)
    assert t.hit["vector"]["전체"][5] == 1
    assert t.hit["vector"]["논문"][3] == 1
    # hybrid: 1, 3, 없음 -> 한국 공보 Hit@3 = 1
    assert t.hit["hybrid"]["한국 공보"][3] == 1
    assert t.hit["hybrid"]["논문"][10] == 0


def test_CQ와_한_방식만_찾은_줄():
    t = compare({"bm25": BM25, "vector": VEC, "hybrid": HYB}, k=10)
    assert t.cq == {"bm25": 2, "vector": 0, "hybrid": 1}
    # a: 셋 다 찾음. b: vector·hybrid. c: vector만 (bm25 12위는 k=10 밖)
    assert t.only == {"bm25": 0, "vector": 1, "hybrid": 0}


def test_k가_작으면_상위_k_기준으로_센다():
    t = compare({"bm25": BM25, "vector": VEC, "hybrid": HYB}, k=1)
    assert t.cq == {"bm25": 2, "vector": 3, "hybrid": 2}
    assert t.only == {"bm25": 0, "vector": 0, "hybrid": 0}


def test_마크다운에_묶음과_방식이_나온다():
    text = render(compare({"bm25": BM25, "vector": VEC, "hybrid": HYB}, k=10))
    assert "### 한국 공보 (줄 2개)" in text
    assert "| vector | 0 | 1 |" in text
    assert "그 밖" not in text


# ---- 빈 입력 ----------------------------------------------------------


def test_논문_줄이_없으면_줄_없음과_경고():
    a = rows([("a", "KR1", 1)])
    b = rows([("a", "KR1", 2)])
    t = compare({"x": a, "y": b}, k=10)
    assert t.hit["x"]["논문"][1] is None
    assert any("논문" in w for w in t.warnings)
    assert "줄 없음" in render(t)


# ---- 실패 -------------------------------------------------------------


def test_row_id_집합이_다르면_오류와_다른_줄_수():
    with pytest.raises(CompareError, match="서로 다른 줄 2개"):
        compare(
            {
                "x": rows([("a", "KR1", 1), ("b", "KR1", 1)]),
                "y": rows([("a", "KR1", 1), ("c", "KR1", 1)]),
            },
            10,
        )


def test_그_밖_doc_id는_그_밖으로_세고_경고(caplog):
    assert group_of(["JP1"]) == "그 밖"
    assert group_of([]) == "그 밖"
    t = compare({"x": rows([("a", "JP1", 1)]), "y": rows([("a", "JP1", 1)])}, 10)
    assert t.n["그 밖"] == 1
    assert any("그 밖" in w for w in t.warnings)
    assert "### 그 밖" in render(t)


def test_US_doc_id는_미국_공보로_세고_그_밖_경고는_없다():
    assert group_of(["US1"]) == "미국 공보"
    x = rows([("a", "KR1", 1), ("b", "US1", 2), ("c", "US2", None)])
    y = rows([("a", "KR1", 3), ("b", "US1", None), ("c", "US2", 1)])
    t = compare({"x": x, "y": y}, 10)
    assert t.n["미국 공보"] == 2
    assert t.n["그 밖"] == 0
    assert t.hit["x"]["미국 공보"][1] == 0
    assert t.hit["x"]["미국 공보"][3] == pytest.approx(1 / 2)
    assert t.hit["y"]["미국 공보"][1] == pytest.approx(1 / 2)
    assert not any("그 밖" in w for w in t.warnings)
    assert "### 미국 공보 (줄 2개)" in render(t)


def _표(g, a, b, c):
    """묶음 하나의 표 조각 (줄 모양은 m2-i2 카드의 비교 표와 같다)."""
    return (
        f"### {g}\n| 방식 | Hit@1 | Hit@3 | Hit@5 | Hit@10 |\n|---|---|---|---|---|\n"
        + "".join(
            f"| {m} | {' | '.join(v)} |\n"
            for m, v in zip(("bm25", "vector", "hybrid"), (a, b, c), strict=True)
        )
        + "\n"
    )


def test_한국과_논문만_있으면_표_전체가_손으로_쓴_글과_같다():
    # 손 계산: 순위 bm25 1/없음/12, vector 4/2/3, hybrid 1/3/없음 (a·b는 KR, c는 논문)
    expected = (
        _표(
            "전체 (줄 3개)",
            ["0.333"] * 4,
            ["0.000", "0.667", "1.000", "1.000"],
            ["0.333", "0.667", "0.667", "0.667"],
        )
        + _표(
            "한국 공보 (줄 2개)",
            ["0.500"] * 4,
            ["0.000", "0.500", "1.000", "1.000"],
            ["0.500", "1.000", "1.000", "1.000"],
        )
        + _표("논문 (줄 1개)", ["0.000"] * 4, ["0.000", "1.000", "1.000", "1.000"], ["0.000"] * 4)
        + "### CQ와 한 방식만 찾은 줄 (상위 10 기준)\n"
        "| 방식 | CQ (상위 10에 없음) | 이 방식만 찾은 줄 |\n|---|---|---|\n"
        "| bm25 | 2 | 0 |\n| vector | 0 | 1 |\n| hybrid | 1 | 0 |\n"
    )
    assert render(compare({"bm25": BM25, "vector": VEC, "hybrid": HYB}, k=10)) == expected


def test_묶음_제목_순서는_논문_미국_공보_그_밖():
    x = rows([("a", "KR1", 1), ("c", "NPL-x-1", 1), ("d", "US1", 1), ("e", "JP1", 1)])
    text = render(compare({"x": x, "y": x}, k=10))
    heads = [line for line in text.splitlines() if line.startswith("### ")]
    assert [h.split(" (")[0] for h in heads[:5]] == [
        "### 전체",
        "### 한국 공보",
        "### 논문",
        "### 미국 공보",
        "### 그 밖",
    ]


def write(path, rs):
    path.write_text(
        "".join(
            json.dumps(
                {
                    "row_id": r.row_id,
                    "doc_ids": r.doc_ids,
                    "first_hit_rank": r.first_hit_rank,
                    "k_max": r.k_max,
                }
            )
            + "\n"
            for r in rs
        ),
        encoding="utf-8",
    )
    return path


def test_CLI_표를_찍고_out에_쓴다(tmp_path, capsys):
    p1, p2 = write(tmp_path / "a.jsonl", BM25), write(tmp_path / "b.jsonl", VEC)
    out = tmp_path / "t.md"
    assert main(["--rows", f"bm25={p1}", f"vector={p2}", "--k", "10", "--out", str(out)]) == 0
    assert "Hit@10" in capsys.readouterr().out
    assert "### 전체" in out.read_text(encoding="utf-8")


def test_CLI_이름_경로_꼴이_아니면_1(tmp_path, capsys):
    p1 = write(tmp_path / "a.jsonl", BM25)
    assert main(["--rows", f"bm25={p1}", str(p1)]) == 1
    assert "이름=경로" in capsys.readouterr().err


def test_CLI_row_id가_다르면_1(tmp_path, capsys):
    p1 = write(tmp_path / "a.jsonl", BM25)
    p2 = write(tmp_path / "b.jsonl", BM25[:2])
    assert main(["--rows", f"x={p1}", f"y={p2}"]) == 1
    assert "row_id 집합이 다르다" in capsys.readouterr().err


def test_CLI_없는_파일은_1(tmp_path):
    p1 = write(tmp_path / "a.jsonl", BM25)
    assert main(["--rows", f"x={p1}", f"y={tmp_path / 'none.jsonl'}"]) == 1


def test_k가_채점_k_max보다_크면_오류():
    small = [RowHit("a", ["KR1"], 1, 5)]
    with pytest.raises(CompareError, match="k_max|가장 큰 k"):
        compare({"x": small, "y": small}, k=10)
    # k_max 5면 Hit 열은 5까지만 찍는다
    t = compare({"x": small, "y": small}, k=5)
    assert t.hit_ks == (1, 3, 5)


def test_CLI_k가_k_max보다_크면_1(tmp_path, capsys):
    small = [RowHit("a", ["KR1"], 1, 5)]
    p1, p2 = write(tmp_path / "a.jsonl", small), write(tmp_path / "b.jsonl", small)
    assert main(["--rows", f"x={p1}", f"y={p2}", "--k", "10"]) == 1
    assert "가장 큰 k" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["true", '"2"', "1.5", "0", "-1"])
def test_first_hit_rank가_정수나_null이_아니면_1(tmp_path, capsys, bad):
    p1 = write(tmp_path / "a.jsonl", BM25)
    p2 = tmp_path / "b.jsonl"
    p2.write_text(
        '{"row_id": "a", "doc_ids": ["KR1"], "first_hit_rank": ' + bad + ', "k_max": 10}\n',
        encoding="utf-8",
    )
    assert main(["--rows", f"x={p1}", f"y={p2}"]) == 1
    assert "모양이 틀림" in capsys.readouterr().err
