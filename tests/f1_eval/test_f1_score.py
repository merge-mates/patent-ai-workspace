"""F1 채점 (eval/f1/score.py). 정답 꼴 예측 대 정답 꼴 정답.

gold_ok.json 칸 수 (이슈 #20 task 3 점수 단위):
- 기본 8
- 거절이유 3 x 4 = 12
- 인용 2 x 2 = 4
- 청구항 줄 13: 줄1(있음·인용·쪽) 3, 줄2 3, 줄3(+같은 취지) 4, 줄4 명확성(있음·표현·쪽) 3
합계 37.
"""

import copy
import json
from pathlib import Path

import pytest

from eval.common.errors import EvalError
from eval.common.scores import check_scores
from eval.f1.config import F1EvalConfig
from eval.f1.gold import F1Gold
from eval.f1.pred import F1Pred
from eval.f1.score import oa_key, score_f1
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "f1_eval"
TOTAL = 37


def _gold_dict() -> dict:
    return json.loads((FIX / "gold_ok.json").read_text(encoding="utf-8"))


def _gold(d: dict | None = None) -> F1Gold:
    return F1Gold.model_validate(d or _gold_dict())


def _pred_dict(d: dict | None = None) -> dict:
    p = copy.deepcopy(d or _gold_dict())
    for k in ("gold_version", "source", "reviewed"):
        p.pop(k)
    return p


def _pred(p: dict) -> F1Pred:
    return F1Pred.model_validate(p)


CFG = F1EvalConfig(experiment="m1-i3-f1-x", goldset="tune", goldset_version=1, impl="jaea")


def _score(golds, preds, pages=None):
    return score_f1(CFG, golds, preds, pages, commit="abc", gold_sha256="0" * 64)


def _one(p: dict, pages=None):
    g = _gold()
    return _score([g], {oa_key(g): _pred(p)}, pages)


# ---- 평소


def test_예측이_정답과_같으면_모두_1이고_지어낸_값_0():
    s = _one(_pred_dict())
    m = s["metrics"]
    assert m["field_accuracy"] == 1
    assert m["field_accuracy_micro"] == 1
    for group in ("basic", "rejections", "citations", "claim_rows"):
        assert m[f"field_accuracy.{group}"] == 1
    assert m["location_recall"] == 1
    assert m["location_exact"] == 1
    assert m["fabricated_values"] == 0
    assert s["n"] == 1
    # 줄2(위치 없음만)와 줄3(같은 취지만)은 위치 채점에서 빠진다
    assert s["failures"]["excluded_location_none"] == 1
    assert s["failures"]["excluded_location_same_as"] == 1
    assert s["failures"]["missing_prediction"] == 0
    check_scores(s)  # 공통 scores.json 모양을 지킨다


def test_scores에_출원번호가_없다():
    text = json.dumps(_one(_pred_dict()), ensure_ascii=False)
    assert "1020990000001" not in text
    assert "952099000000001" not in text


def test_칸_하나가_틀리면_36_37():
    p = _pred_dict()
    p["notice_kind"]["value"] = "final"
    m = _one(p)["metrics"]
    assert m["field_accuracy"] == pytest.approx(36 / 37)
    assert m["field_accuracy_micro"] == pytest.approx(36 / 37)
    assert m["field_accuracy.basic"] == pytest.approx(7 / 8)
    assert m["fabricated_values"] == 0


def test_글자_칸은_줄바꿈이_달라도_맞음():
    p = _pred_dict()
    p["rejections"][0]["article"] = "특허법\n제29조제2항"
    p["notice_date"]["text"] = "2099. 01. 26."
    assert _one(p)["metrics"]["field_accuracy"] == 1


def test_미국_키에_종류_코드가_없어도_맞음():
    p = _pred_dict()
    p["citations"][1]["key"] = "US1234567"
    assert _one(p)["metrics"]["field_accuracy.citations"] == 1


def test_줄_쪽이_범위_안이면_맞고_밖이면_틀림():
    p = _pred_dict()
    p["claim_rows"][2]["page"] = 4  # 정답 3~4
    assert _one(p)["metrics"]["field_accuracy"] == 1
    p["claim_rows"][2]["page"] = 5
    assert _one(p)["metrics"]["field_accuracy"] == pytest.approx(36 / 37)


def test_명확성_표현이_겹치면_맞고_안_겹치면_틀림():
    p = _pred_dict()
    p["claim_rows"][3]["clarity_terms"] = ["프리뷰 이미지"]
    assert _one(p)["metrics"]["field_accuracy"] == 1
    p["claim_rows"][3]["clarity_terms"] = ["다른 표현"]
    assert _one(p)["metrics"]["field_accuracy"] == pytest.approx(36 / 37)


def test_같은_취지는_하나만_겹쳐도_맞음():
    p = _pred_dict()
    p["claim_rows"][2]["same_as"] = ["claim:1", "claim:2"]
    assert _one(p)["metrics"]["field_accuracy"] == 1


def test_청구항_줄이_빠지면_그_줄_칸이_다_틀림():
    p = _pred_dict()
    del p["claim_rows"][2]  # 줄3: 4칸
    m = _one(p)["metrics"]
    assert m["field_accuracy"] == pytest.approx(33 / 37)
    assert m["fabricated_values"] == 0


# ---- 짚은 위치


def test_위치_다섯_중_셋이면_재현율_0_6_완전일치_0():
    p = _pred_dict()
    p["claim_rows"][0]["locations"] = {"D1": ["[0014]", "도 4b"], "D2": ["청구항 1"]}
    m = _one(p)["metrics"]
    assert m["location_recall"] == pytest.approx(0.6)
    assert m["location_exact"] == 0
    assert m["fabricated_values"] == 0


def test_정답에_없는_위치를_더하면_지어낸_값():
    p = _pred_dict()
    p["claim_rows"][0]["locations"]["D1"].append("[0099]")
    m = _one(p)["metrics"]
    assert m["location_recall"] == 1
    assert m["location_exact"] == 0
    assert m["fabricated_values"] == 1


# ---- 지어낸 값


def test_정답이_없음인데_값을_내면_지어낸_값():
    p = _pred_dict()
    p["allowable_claims"]["value"] = [3]
    p["amendment_note"]["value"] = "보정하면 됨"
    m = _one(p)["metrics"]
    assert m["fabricated_values"] == 2
    assert m["field_accuracy"] == pytest.approx(35 / 37)


def test_정답에_없는_줄_거절이유_인용_청구항_번호를_더하면_하나씩():
    p = _pred_dict()
    p["claim_rows"].append(
        {"claim": 3, "rejection": 2, "citations": [], "locations": {}, "same_as": [], "page": 4}
    )
    p["rejections"].append(
        {
            "no": 4,
            "kind": "novelty",
            "article": "x",
            "supported": True,
            "targets": {"value": [1], "text": "x"},
            "page": 1,
        }
    )
    p["citations"].append({"label": "D3", "text": "x", "key": "JP2020123456A", "rejections": [4]})
    p["rejections"][1]["targets"]["value"] = [2, 3]  # 3을 더함
    m = _one(p)["metrics"]
    assert m["fabricated_values"] == 4
    # 더한 줄·거절이유·인용은 정답 칸 수를 바꾸지 않는다. 대상 청구항 칸 하나만 틀림
    assert m["field_accuracy"] == pytest.approx(36 / 37)


# ---- 빈 경우


def test_예측이_없는_OA는_0점이고_건수를_센다():
    g1 = _gold()
    d2 = _gold_dict()
    d2["application_number"]["value"] = "1020990000002"
    g2 = _gold(d2)
    s = _score([g1, g2], {oa_key(g1): _pred(_pred_dict())})
    assert s["n"] == 2
    assert s["failures"]["missing_prediction"] == 1
    assert s["metrics"]["field_accuracy"] == pytest.approx(0.5)
    assert s["metrics"]["field_accuracy_micro"] == pytest.approx(0.5)
    assert s["metrics"]["location_recall"] == pytest.approx(0.5)


def test_예측이_하나도_없으면_실패():
    with pytest.raises(EvalError, match="예측"):
        _score([_gold()], {})


def test_정답이_0개면_실패():
    with pytest.raises(EvalError, match="정답"):
        _score([], {})


# ---- 확인하지 않은 원문 위치 (쪽 글자)


def _pt(texts: list[str]) -> PageText:
    """쪽 글자 목록 -> PageText (extract_pages가 내는 모양)."""
    ok = Status(value=StatusValue.CONFIRMED, checked="글자 층 있음")
    return PageText(
        document_id="d",
        pages=[Page(page=i, text=x, status=ok) for i, x in enumerate(texts, start=1)],
        status=ok,
    )


def _pages_ok() -> list[str]:
    g = _gold_dict()
    p1 = "\n".join(
        [
            g["application_number"]["text"],
            g["dispatch_number"]["text"],
            "발송일자 " + g["notice_date"]["text"],
            g["response_due"]["text"],
            "심사 대상 " + g["examined_claims"]["text"],
        ]
        + [r["targets"]["text"] for r in g["rejections"]]
        + [r["article"] for r in g["rejections"]]
    )
    p2 = "  ".join(c["text"] for c in g["citations"])
    return [p1, p2, "", ""]


def test_쪽_글자가_없으면_지표를_빼고_건수를_센다():
    s = _one(_pred_dict())
    assert "unverified_locations" not in s["metrics"]
    assert s["failures"]["pages_missing"] == 1


def test_원문이_그_쪽에_다_있으면_0():
    g = _gold()
    s = _score([g], {oa_key(g): _pred(_pred_dict())}, {oa_key(g): _pt(_pages_ok())})
    assert s["metrics"]["unverified_locations"] == 0
    assert s["failures"]["pages_missing"] == 0


def test_원문이_붙은_쪽에_없으면_하나씩_센다():
    g = _gold()
    pages = _pages_ok()
    pages[1] = pages[1].replace("공개특허공보", "")  # D1 원문이 2쪽에 없음
    p = _pred_dict()
    p["notice_date"]["page"] = 2  # 통지일 원문은 1쪽에만 있음
    s = _score([g], {oa_key(g): _pred(p)}, {oa_key(g): _pt(pages)})
    assert s["metrics"]["unverified_locations"] == 2


def test_두_쪽에_걸친_판단_문장은_앱처럼_시작_쪽에서_확인된다():
    # 앱 원문 대조(#125)와 같은 규칙: 머리말·꼬리말을 빼고 이웃한 두 쪽을 이어 찾는다
    g = _gold()
    pages = _pages_ok()
    pages[2] = "10-2099-0000001\n청구항 1은 D1, D2로 쉽\n- 3 -"
    pages[3] = "10-2099-0000001\n게 발명할 수 있다\n4/6"
    p = _pred_dict()
    p["claim_rows"][0]["text"] = "청구항 1은 D1, D2로 쉽게 발명할 수 있다"
    p["claim_rows"][1]["text"] = "게 발명할 수 있다"  # 통째로 4쪽에만 있는데 3쪽이라 함
    s = _score([g], {oa_key(g): _pred(p)}, {oa_key(g): _pt(pages)})
    assert s["metrics"]["unverified_locations"] == 1


def test_안_낸_칸은_정답이_없음이어도_틀림():
    # 앱이 '확인되지 않음'으로 낸 칸(given=False)은 값이 None이어도 '없음'과 같다고 보지 않는다
    p = _pred_dict()
    p["amendment_note"]["given"] = False
    m = _one(p)["metrics"]
    assert m["field_accuracy"] == pytest.approx(36 / 37)
    assert m["fabricated_values"] == 0


def test_OA_평균과_전체_합산이_갈린다():
    # 칸 수가 다른 OA 둘: OA1은 37칸 다 맞음, OA2는 거절이유 하나만 남겨 칸 수를 줄이고 하나 틀림
    g1 = _gold()
    d2 = _gold_dict()
    d2["application_number"]["value"] = "1020990000002"
    d2["rejections"] = [d2["rejections"][1]]  # 명확성(2)만
    d2["citations"] = []
    d2["claim_rows"] = [d2["claim_rows"][3]]
    g2 = _gold(d2)  # 칸: 기본 8 + 거절이유 4 + 줄 3 = 15
    p2 = _pred_dict(d2)
    p2["notice_kind"]["value"] = "final"  # 15칸 중 14 맞음
    s = _score([g1, g2], {oa_key(g1): _pred(_pred_dict()), oa_key(g2): _pred(p2)})
    assert s["metrics"]["field_accuracy"] == pytest.approx((1 + 14 / 15) / 2)
    assert s["metrics"]["field_accuracy_micro"] == pytest.approx((37 + 14) / (37 + 15))


# ---- cost: read_oa 실행 호출 기록 합치기 (이슈 #156)


def _rec(**kw) -> dict:
    """호출 기록 한 줄 (CallRecord 꼴 + case). 기본은 가격 있는 정상 호출."""
    base = {
        "run_id": "r1",
        "step": "read",
        "model": "m",
        "input_tokens": 100,
        "output_tokens": 10,
        "cost": 0.5,
        "elapsed_ms": 5,
        "from_cache": False,
        "attempt": 1,
        "outcome": "ok",
        "transport_try": 1,
        "case": "x",
    }
    return base | kw


def _cost(calls):
    g = _gold()
    return score_f1(
        CFG,
        [g],
        {oa_key(g): _pred(_pred_dict())},
        None,
        commit="abc",
        gold_sha256="0" * 64,
        calls=calls,
    )["cost"]


def test_호출_기록이_있으면_토큰_호출수_usd를_합친다():
    calls = [
        _rec(),
        _rec(input_tokens=200, output_tokens=20, cost=0.25, stop_reason="end_turn"),
        _rec(from_cache=True, outcome="cache_hit", cost=0.0),  # 캐시 적중: 호출 수에서 뺌
        _rec(input_tokens=0, output_tokens=0, cost=None, outcome="limit_exceeded"),  # 막힘: 뺌
        _rec(input_tokens=0, output_tokens=0, cost=None, outcome="transport_error"),  # 셈
    ]
    c = _cost(calls)
    assert c["external_calls"] == 3
    # 토큰도 실제로 부른 호출만 (100 + 200 + 전송 오류 0). 캐시 적중 토큰은 따로 칸
    assert c["input_tokens"] == 300
    assert c["output_tokens"] == 30
    assert c["cached_input_tokens"] == 100
    assert c["cached_output_tokens"] == 10
    assert c["usd"] == 0.75


def test_캐시_적중만_있으면_호출_토큰_usd가_0이다():
    c = _cost([_rec(from_cache=True, outcome="cache_hit", cost=0.0, transport_try=0)])
    assert (c["external_calls"], c["input_tokens"], c["output_tokens"], c["usd"]) == (0, 0, 0, 0)
    assert c["cached_input_tokens"] == 100


def test_같은_기록이_겹치면_경고(caplog):
    _cost([_rec(), _rec()])
    assert "겹친" in caplog.text


def test_다른_시도는_겹침으로_보지_않는다(caplog):
    _cost([_rec(), _rec(attempt=2, transport_try=1, elapsed_ms=7)])
    assert "겹친" not in caplog.text


def test_기록의_사건_수가_채점한_OA보다_적으면_경고(caplog):
    d2 = _gold_dict()
    d2["application_number"]["value"] = "1020990000002"
    g1, g2 = _gold(), _gold(d2)
    score_f1(
        CFG,
        [g1, g2],
        {oa_key(g1): _pred(_pred_dict())},
        None,
        commit="abc",
        gold_sha256="0" * 64,
        calls=[_rec(case="a")],
    )
    assert "사건 1개" in caplog.text and "OA 2건" in caplog.text


def test_기록에_case가_없으면_사건_수를_보지_않는다(caplog):
    rec = _rec()
    del rec["case"]
    _cost([rec])
    assert "사건" not in caplog.text


def test_호출_기록이_없으면_0과_경고(caplog):
    c = _cost(None)
    assert (c["usd"], c["input_tokens"], c["output_tokens"], c["external_calls"]) == (0, 0, 0, 0)
    assert (c["cached_input_tokens"], c["cached_output_tokens"]) == (0, 0)
    assert "--calls" in caplog.text


def test_호출_기록이_빈_목록이면_0과_경고(caplog):
    c = _cost([])
    assert c["external_calls"] == 0
    assert "호출 기록" in caplog.text


def test_가격이_없으면_usd를_비우고_경고(caplog):
    c = _cost([_rec(), _rec(cost=None), _rec(cost=None)])
    assert c["usd"] is None
    assert c["external_calls"] == 3
    assert "usd를 비움" in caplog.text
    assert "2줄" in caplog.text


def test_응답이_없는_전송_오류의_None은_usd를_비우지_않는다(caplog):
    c = _cost([_rec(), _rec(input_tokens=0, output_tokens=0, cost=None, outcome="transport_error")])
    assert c["usd"] == 0.5
    assert "usd를 비움" not in caplog.text


def test_토큰을_모르는_호출이_있으면_usd와_그_칸의_토큰_합을_비우고_경고(caplog):
    # 글을 받는 중 스트림이 끊긴 호출 (#194): 입력은 받았고 출력 토큰·비용이 None(확인되지 않음)
    unknown = _rec(input_tokens=1000, output_tokens=None, cost=None, outcome="transport_error")
    c = _cost([_rec(), unknown])
    assert c["usd"] is None
    assert c["input_tokens"] == 1100  # 입력은 다 알아서 합이 남는다
    assert c["output_tokens"] is None  # 모르는 줄이 섞이면 일부만 더한 합을 두지 않는다
    assert c["external_calls"] == 2
    assert "확인되지 않은" in caplog.text


def test_호출_기록_파일의_토큰_None은_읽힌다(tmp_path):
    assert len(_load(tmp_path, [_rec(input_tokens=None, output_tokens=None, cost=None)])) == 1


def _load(tmp_path, data):
    from eval.f1.score import load_calls

    f = tmp_path / "calls.json"
    f.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return load_calls(f)


def test_호출_기록_파일을_읽으면_모르는_키는_무시한다(tmp_path):
    assert len(_load(tmp_path, [_rec(stop_reason="end_turn", extra=1)])) == 1


def test_호출_기록에_오류_종류_칸이_있어도_읽고_합친다(tmp_path):
    # #228: 출력 검사 실패 호출에 invalid_kind(짧은 코드) 칸이 생겼다. 옛 기록은 칸이 없다
    calls = _load(
        tmp_path,
        [
            _rec(invalid_kind=None),
            _rec(outcome="invalid_output", invalid_kind="missing_key,bad_value"),
            _rec(),
        ],
    )
    assert len(calls) == 3
    from eval.f1.score import sum_calls

    assert sum_calls(calls, 1)["external_calls"] == 3


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"a": 1}',
        "[1]",
        json.dumps([{k: v for k, v in _rec().items() if k != "from_cache"}]),
        json.dumps([_rec(input_tokens="100")]),
        json.dumps([_rec(cost="0.5")]),
        json.dumps([_rec(from_cache=1)]),
    ],
)
def test_호출_기록_파일이_틀리면_파일_이름만_말하고_멈춘다(tmp_path, bad):
    with pytest.raises(EvalError) as e:
        _load(tmp_path, bad)
    assert "calls.json" in str(e.value)
    assert "not json" not in str(e.value)


def test_호출_기록_파일이_없으면_멈춘다(tmp_path):
    from eval.f1.score import load_calls

    with pytest.raises(EvalError):
        load_calls(tmp_path / "nope.json")
