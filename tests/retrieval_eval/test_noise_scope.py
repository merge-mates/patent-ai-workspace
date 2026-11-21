"""노이즈 검색 범위 만들기 (이슈 #178 B안: tune 인용문헌 전체를 한 풀로).

기대값은 이슈 #178 '넣는 조건'에서 가져온다: 우선일 전 공개만, 그 출원 자신·정답 인용문헌과
같은 특허의 다른 공보·비특허 문헌은 뺀다. 정답 문헌은 늘 범위에 남는다.
번호·날짜는 모두 지어낸 값이다.
"""

import json
from datetime import date

import pytest
import yaml

from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldItem, GoldRow
from eval.retrieval.noise_scope import (
    PoolTable,
    build_noise_scope,
    load_noise_scope,
    main,
)

ITEM = GoldItem(kind="paragraph", start=1, end=1, label="[0001]")


def row(row_id: str, doc: str) -> GoldRow:
    return GoldRow(row_id=row_id, corpus="cite", query="가짜 질의", doc_ids=[doc], items=[ITEM])


def table(**over) -> PoolTable:
    base = {
        "docs": {
            # 사건 A(우선일 2015-01-01)의 정답 공개 A와 같은 특허의 등록 B1
            "KR1000A": {"app_no": "P1", "date": date(2010, 1, 1)},
            "KR1000B1": {"app_no": "P1", "date": date(2012, 1, 1)},
            # 다른 사건이 인용한 문헌들
            "KR2000A": {"app_no": "P2", "date": date(2011, 1, 1)},
            "KR3000A": {"app_no": "P3", "date": date(2016, 1, 1)},  # 사건 A 우선일 뒤
            "KR4000A": {"app_no": "P4", "date": date(2015, 1, 1)},  # 우선일 당일 (뺌)
            "KR5000A": {"app_no": "PA", "date": date(2014, 6, 1)},  # 사건 A 자신의 공보
            "NPL-paper-2012": {"app_no": None, "date": date(2012, 1, 1)},
        },
        "oas": {
            "OA1": {"app_no": "PA", "priority_date": date(2015, 1, 1)},
            "OA2": {"app_no": "PB", "priority_date": date(2020, 1, 1)},
        },
    }
    base.update(over)
    return PoolTable.model_validate(base)


def test_넣는_조건대로_거른다():
    rows = [row("OA1:r1:c1:KR1000A", "KR1000A")]
    scope, rep = build_noise_scope(rows, table())
    # 정답 KR1000A + 우선일 전에 공개된 다른 특허 KR2000A만 남는다
    assert scope["OA1:r1:c1:KR1000A"] == ["KR1000A", "KR2000A"]
    assert rep.excluded == {
        "after_priority": 2,  # KR3000A, KR4000A(당일)
        "own_application": 1,  # KR5000A
        "same_patent": 1,  # KR1000B1
        "npl": 1,
    }


def test_정답_문헌은_우선일_뒤여도_비특허여도_남는다():
    rows = [row("OA1:r1:c1:NPL-paper-2012", "NPL-paper-2012"), row("OA1:r2:c1:KR3000A", "KR3000A")]
    scope, _ = build_noise_scope(rows, table())
    assert "NPL-paper-2012" in scope["OA1:r1:c1:NPL-paper-2012"]
    assert scope["OA1:r2:c1:KR3000A"][0] == "KR3000A"


def test_정답이_비특허면_같은_특허_규칙은_안_쓴다():
    # 비특허 문헌은 출원번호가 없다. None끼리 같다고 다른 문헌을 빼면 안 된다
    rows = [row("OA2:r1:c1:NPL-paper-2012", "NPL-paper-2012")]
    scope, rep = build_noise_scope(rows, table())
    assert scope["OA2:r1:c1:NPL-paper-2012"] == [
        "NPL-paper-2012",
        "KR1000A",
        "KR1000B1",
        "KR2000A",
        "KR3000A",
        "KR4000A",
        "KR5000A",
    ]
    assert rep.excluded["same_patent"] == 0


def test_표에_없는_OA면_멈춘다():
    with pytest.raises(RetrievalEvalError, match="OA9"):
        build_noise_scope([row("OA9:r1:c1:KR1000A", "KR1000A")], table())


def test_표에_없는_정답_문헌이면_멈춘다():
    with pytest.raises(RetrievalEvalError, match="KR7777A"):
        build_noise_scope([row("OA1:r1:c1:KR7777A", "KR7777A")], table())


def test_특허_문헌에_출원번호가_없으면_표를_못_읽는다():
    with pytest.raises(ValueError):
        PoolTable.model_validate(
            {"docs": {"KR1000A": {"app_no": None, "date": "2010-01-01"}}, "oas": {}}
        )


def test_빈_풀이면_멈춘다():
    with pytest.raises(ValueError):
        PoolTable.model_validate({"docs": {}, "oas": {}})


def _write_gold(path, rows):
    path.write_text(
        "".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


@pytest.fixture
def goldsets_root(tmp_path):
    root = tmp_path / "goldsets"
    d = root / "tune" / "retrieval"
    d.mkdir(parents=True)
    _write_gold(d / "cite_gold.jsonl", [row("OA1:r1:c1:KR1000A", "KR1000A")])
    (d / "cite_pool.yaml").write_text(
        yaml.safe_dump(table().model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    return root


def test_명령은_파일을_쓰고_다시_읽힌다(goldsets_root):
    argv = [
        "--goldsets-root",
        str(goldsets_root),
        "--gold",
        "retrieval/cite_gold.jsonl",
        "--pool",
        "retrieval/cite_pool.yaml",
        "--out",
        "retrieval/cite_noise_b.jsonl",
    ]
    assert main(argv) == 0
    out = goldsets_root / "tune" / "retrieval" / "cite_noise_b.jsonl"
    assert load_noise_scope(out) == {"OA1:r1:c1:KR1000A": ["KR1000A", "KR2000A"]}


def test_명령은_세트_폴더_밖에_쓰지_않는다(goldsets_root):
    argv = ["--goldsets-root", str(goldsets_root), "--out", "../noise.jsonl"]
    assert main(argv) == 1
    assert not (goldsets_root / "noise.jsonl").exists()


def test_범위_파일_읽기_검사(tmp_path):
    p = tmp_path / "n.jsonl"
    p.write_text("", encoding="utf-8")
    with pytest.raises(RetrievalEvalError, match="0줄"):
        load_noise_scope(p)
    p.write_text('{"row_id": "a", "scope_doc_ids": []}\n', encoding="utf-8")
    with pytest.raises(RetrievalEvalError, match="1번째"):
        load_noise_scope(p)
    p.write_text(
        '{"row_id": "a", "scope_doc_ids": ["X"]}\n{"row_id": "a", "scope_doc_ids": ["X"]}\n',
        encoding="utf-8",
    )
    with pytest.raises(RetrievalEvalError, match="중복"):
        load_noise_scope(p)
