"""F1 정답 형식 검사 (eval/f1/gold.py, docs/evaluation/f1-oa-gold.md 4절).

fixture는 4절 예시를 바탕으로 지어낸 값이다. 경우마다 칸 하나를 망가뜨려 본다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from eval.common.errors import EvalError
from eval.f1.gold import load_f1_gold

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "f1_eval"
# 진짜 정답처럼 파일 이름에 출원번호·발송번호 (메시지에 새면 안 된다)
NAME = "1020990000001_952099000000001.json"


def _base() -> dict:
    return json.loads((FIX / "gold_ok.json").read_text(encoding="utf-8"))


def _write(tmp_path, *golds) -> Path:
    d = tmp_path / "f1"
    d.mkdir()
    for i, g in enumerate(golds):
        # 두 번째부터는 이름 순서로 뒤에 오게 (첫 파일과 겹치지 않게)
        name = NAME if i == 0 else f"10209900001{i:02d}_95209900000{i:04d}.json"
        (d / name).write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return d


def _fails(tmp_path, gold, match):
    d = _write(tmp_path, gold)
    with pytest.raises(EvalError, match=match) as e:
        load_f1_gold(d, expected_version=1)
    msg = str(e.value)
    # 파일 이름(출원번호)·원문 글자는 메시지에 넣지 않는다
    assert "1020990000001" not in msg
    assert "952099000000001" not in msg
    return msg


# ---- 평소


def test_4절_예시가_읽힌다(tmp_path):
    golds = load_f1_gold(_write(tmp_path, _base()), expected_version=1)
    assert len(golds) == 1
    g = golds[0]
    assert g.notice_kind.value == "initial"
    assert [r.kind for r in g.rejections] == ["inventive_step", "clarity", "other"]
    assert g.claim_rows[0].locations["D1"] == ["[0014]", "[0080]-[0081]", "도 4b"]
    assert g.claim_rows[2].same_as == ["claim:1"]
    assert g.claim_rows[2].page_end == 4


def test_파일_이름_순서로_읽는다(tmp_path):
    a, b = _base(), _base()
    b["examined_claims"]["value"] = [1, 2, 3, 4]
    golds = load_f1_gold(_write(tmp_path, a, b), expected_version=1)
    assert [len(g.examined_claims.value) for g in golds] == [3, 4]


def test_문서_밖이던_네_칸도_받는다(tmp_path):
    g = _base()
    g["notice_kind"]["label"] = "최초거절이유통지"
    g["reviewed"] = {"by": "검수자", "date": "2099-01-01", "method": "원문 대조", "scope": "전체"}
    load_f1_gold(_write(tmp_path, g), expected_version=1)


@pytest.mark.parametrize(
    "loc", ["요약", "도 4c", "청구항 9", "3:5-10", "3쪽 3.1절 1-5줄", "3쪽 3.1절 4쪽 전체", "310"]
)
def test_정답_규칙의_여러_위치_꼴을_받는다(tmp_path, loc):
    g = _base()
    g["claim_rows"][0]["locations"]["D1"] = [loc]
    load_f1_gold(_write(tmp_path, g), expected_version=1)


# ---- 빈 경우


def test_폴더에_파일이_0개면_실패(tmp_path):
    (tmp_path / "f1").mkdir()
    with pytest.raises(EvalError, match="0개"):
        load_f1_gold(tmp_path / "f1", expected_version=1)


def test_폴더가_없으면_실패(tmp_path):
    with pytest.raises(EvalError, match="폴더가 없다"):
        load_f1_gold(tmp_path / "nope", expected_version=1)


def test_청구항_줄이_0개면_경고만(tmp_path, caplog):
    g = _base()
    g["claim_rows"] = []
    with caplog.at_level(logging.WARNING):
        load_f1_gold(_write(tmp_path, g), expected_version=1)
    assert "청구항 줄이 0개" in caplog.text
    assert "1020990000001" not in caplog.text


# ---- 실패 (이유와 함께)


def test_JSON_문법이_틀리면_실패(tmp_path):
    d = tmp_path / "f1"
    d.mkdir()
    (d / NAME).write_text("{ not json", encoding="utf-8")
    with pytest.raises(EvalError, match="1번째.*JSON") as e:
        load_f1_gold(d, expected_version=1)
    assert "1020990000001" not in str(e.value)


def test_gold_version이_기대와_다르면_실패(tmp_path):
    g = _base()
    g["gold_version"] = 2
    _fails(tmp_path, g, r"gold_version이 다르다: 파일 2, VERSION 1")


def test_gold_version이_문자열이면_실패(tmp_path):
    g = _base()
    g["gold_version"] = "tune-f1-v0"
    _fails(tmp_path, g, "gold_version")


def test_모르는_칸은_실패(tmp_path):
    g = _base()
    g["claim_rows"][0]["locaton"] = {}
    _fails(tmp_path, g, r"claim_rows\.0\.locaton")


def test_모르는_kind는_실패(tmp_path):
    g = _base()
    g["rejections"][0]["kind"] = "obviousness"
    _fails(tmp_path, g, r"rejections\.0\.kind")


def test_모르는_notice_kind는_실패(tmp_path):
    g = _base()
    g["notice_kind"]["value"] = "first"
    _fails(tmp_path, g, r"notice_kind\.value")


def test_날짜_칸에_value가_있으면_실패(tmp_path):
    g = _base()
    g["notice_date"]["value"] = "2099-01-26"
    _fails(tmp_path, g, r"notice_date\.value")


@pytest.mark.parametrize("bad", ["[0080-0081]", "[16]", "[0016", "[00016]"])
def test_문단_꼴이_틀리면_실패(tmp_path, bad):
    g = _base()
    g["claim_rows"][0]["locations"]["D1"] = [bad]
    msg = _fails(tmp_path, g, "문단")
    assert "claim_rows.0" in msg


@pytest.mark.parametrize("bad", ["claim1", "claim:0", "row:2", "claim:"])
def test_same_as_꼴이_틀리면_실패(tmp_path, bad):
    g = _base()
    g["claim_rows"][2]["same_as"] = [bad]
    _fails(tmp_path, g, r"claim_rows\.2\.same_as")


def test_라벨_꼴이_틀리면_실패(tmp_path):
    g = _base()
    g["citations"][0]["label"] = "인용발명1"
    _fails(tmp_path, g, r"citations\.0\.label")


def test_쪽이_없는데_basis가_없으면_실패(tmp_path):
    g = _base()
    del g["allowable_claims"]["basis"]
    _fails(tmp_path, g, r"allowable_claims.*basis")


def test_같은_거절이유_순번이_두_번이면_실패(tmp_path):
    g = _base()
    g["rejections"][1]["no"] = 1
    _fails(tmp_path, g, "거절이유 순번")


def test_같은_라벨이_두_번이면_실패(tmp_path):
    g = _base()
    g["citations"][1]["label"] = "D1"
    _fails(tmp_path, g, "라벨")


def test_인용문헌이_없는_거절이유에_쓰였다고_하면_실패(tmp_path):
    g = _base()
    g["citations"][0]["rejections"] = [9]
    _fails(tmp_path, g, r"citations\.0.*거절이유 9")


def test_청구항_줄이_없는_거절이유를_가리키면_실패(tmp_path):
    g = _base()
    g["claim_rows"][0]["rejection"] = 9
    _fails(tmp_path, g, r"claim_rows\.0.*거절이유 9")


def test_청구항_줄_인용이_표에_없는_라벨이면_실패(tmp_path):
    g = _base()
    g["claim_rows"][0]["citations"] = ["D1", "D3"]
    _fails(tmp_path, g, r"claim_rows\.0.*D3")


def test_locations_라벨이_그_줄_인용에_없으면_실패(tmp_path):
    g = _base()
    g["claim_rows"][1]["locations"] = {"D2": ["[0001]"]}
    _fails(tmp_path, g, r"claim_rows\.1.*D2")


def test_명확성_줄에_인용이나_위치가_있으면_실패(tmp_path):
    g = _base()
    g["claim_rows"][3]["citations"] = ["D1"]
    g["claim_rows"][3]["locations"] = {"D1": ["[0001]"]}
    _fails(tmp_path, g, r"claim_rows\.3.*명확성")


def test_명확성이_아닌_줄에_clarity_terms가_있으면_실패(tmp_path):
    g = _base()
    g["claim_rows"][0]["clarity_terms"] = ["상기 프리뷰 이미지"]
    _fails(tmp_path, g, r"claim_rows\.0.*명확성")


def test_지원_안_하는_거절이유에_청구항_줄이_있으면_실패(tmp_path):
    g = _base()
    g["rejections"][2]["targets"]["value"] = [1]
    g["claim_rows"].append(
        {"claim": 1, "rejection": 3, "citations": [], "locations": {}, "same_as": [], "page": 5}
    )
    _fails(tmp_path, g, r"claim_rows\.4.*지원 안 하는")


def test_지원과_kind가_어긋나면_실패(tmp_path):
    g = _base()
    g["rejections"][2]["supported"] = True
    _fails(tmp_path, g, r"rejections\.2.*supported")


def test_청구항_줄의_청구항이_거절이유_대상에_없으면_실패(tmp_path):
    g = _base()
    g["claim_rows"][3]["claim"] = 3
    _fails(tmp_path, g, r"claim_rows\.3.*청구항 3")


def test_same_as가_없는_거절이유를_가리키면_실패(tmp_path):
    g = _base()
    g["claim_rows"][2]["same_as"] = ["rejection:9"]
    _fails(tmp_path, g, r"claim_rows\.2.*rejection:9")


def test_두_번째_파일이_틀리면_순번을_말한다(tmp_path):
    bad = copy.deepcopy(_base())
    bad["rejections"][0]["kind"] = "x"
    d = _write(tmp_path, _base(), bad)
    with pytest.raises(EvalError, match="정답 파일 2번째"):
        load_f1_gold(d, expected_version=1)
