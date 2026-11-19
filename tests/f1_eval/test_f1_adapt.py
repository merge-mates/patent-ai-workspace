"""OAResult -> 정답 꼴 예측 (eval/f1/adapt.py). 확인됨 값만 '냈다'로 본다 (#20 task 5 결정)."""

import json
from pathlib import Path

import pytest
from conftest import AMBIGUOUS, ev  # noqa: E402  (같은 폴더 conftest의 도우미)

from eval.f1.adapt import to_pred
from eval.f1.config import F1EvalConfig
from eval.f1.gold import F1Gold
from eval.f1.score import oa_key, score_f1
from patent_ai.core.schemas.common import Candidate, ExtractedValue, Status, StatusValue

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "f1_eval"
CFG = F1EvalConfig(experiment="x", goldset="tune", goldset_version=1, impl="jaea")


def _gold() -> F1Gold:
    return F1Gold.model_validate(json.loads((FIX / "gold_ok.json").read_text(encoding="utf-8")))


def _score(oa):
    g = _gold()
    return score_f1(CFG, [g], {oa_key(g): to_pred(oa)}, None, commit="x", gold_sha256="0")


def test_정답과_같은_OAResult를_바꿔_채점하면_모두_1(make_oa):
    m = _score(make_oa())["metrics"]
    assert m["field_accuracy"] == 1
    assert m["location_recall"] == 1
    assert m["fabricated_values"] == 0


def test_조문은_코드가_아니라_원문_글자로(make_oa):
    p = to_pred(make_oa())
    assert p.rejections[0].article == "특허법 제29조제2항"
    assert p.rejections[0].kind == "inventive_step"
    assert p.rejections[0].targets.value == [1, 2, 3]
    assert p.rejections[0].targets.text == "청구항 제1항 내지 제3항"
    assert p.rejections[0].page == 1


def test_거절이유마다_있는_인용을_라벨로_묶는다(make_oa):
    p = to_pred(make_oa())
    by = {c.label: c for c in p.citations}
    assert set(by) == {"D1", "D2"}
    assert by["D1"].key == "KR20990000001A"
    assert by["D1"].rejections == [1]
    assert by["D1"].page == 2
    assert by["D1"].text.startswith("공개특허공보")


def test_기본_칸과_심사관_힌트를_옮긴다(make_oa):
    p = to_pred(make_oa())
    assert p.application_number.value == "1020990000001"
    assert p.application_number.text == "10-2099-0000001"
    assert p.notice_date.text == "2099.01.26."
    assert p.notice_kind.value == "initial"
    assert p.allowable_claims.value == []
    assert p.amendment_note.value is None


def test_청구항_줄의_원문과_쪽을_옮긴다(make_oa):
    p = to_pred(make_oa())
    assert p.claim_rows[0].text == "청구항 1은 D1, D2로 쉽게"
    assert p.claim_rows[0].page == 3
    assert p.claim_rows[3].clarity_terms == ["상기 프리뷰 이미지"]


def test_확인되지_않은_값은_안_낸_것으로(make_oa):
    oa = make_oa(application_number=ev("1020990000001", "10-2099-0000001", 1, AMBIGUOUS))
    p = to_pred(oa)
    assert p.application_number.value is None
    assert p.application_number.text is None
    m = _score(oa)["metrics"]
    assert m["field_accuracy"] == pytest.approx(36 / 37)
    assert m["fabricated_values"] == 0


def test_충돌은_안_낸_것으로(make_oa):
    conflict = ExtractedValue(
        status=Status(value=StatusValue.CONFLICT),
        candidates=[
            Candidate(value="initial", source="rule"),
            Candidate(value="final", source="model"),
        ],
    )
    p = to_pred(make_oa(notice_kind=conflict))
    assert p.notice_kind.value is None


def test_조문이_확인되지_않으면_종류_지원도_안_낸다(make_oa):
    oa = make_oa()
    rej = oa.rejections[1]
    bad = rej.model_copy(update={"article": ev("42-4-2", "특허법 제42조제4항제2호", 1, AMBIGUOUS)})
    oa = oa.model_copy(update={"rejections": [oa.rejections[0], bad, oa.rejections[2]]})
    p = to_pred(oa)
    assert p.rejections[1].article is None
    assert p.rejections[1].kind is None
    assert p.rejections[1].supported is None


def test_확인되지_않은_청구항_줄은_뺀다(make_oa):
    from patent_ai.core.schemas.oa_result import ClaimRow

    oa = make_oa()
    rows = list(oa.claim_rows)
    rows[2] = ClaimRow(claim=3, rejection=1, status=AMBIGUOUS)  # 값 없이 번호만 남은 줄
    rows.append(ClaimRow(claim=None, rejection=None, status=AMBIGUOUS))
    p = to_pred(oa.model_copy(update={"claim_rows": rows}))
    assert [(r.claim, r.rejection) for r in p.claim_rows] == [(1, 1), (2, 1), (2, 2)]
    # 빠진 줄3은 칸 4개가 다 틀림, 지어낸 값은 아님
    m = _score(oa.model_copy(update={"claim_rows": rows}))["metrics"]
    assert m["field_accuracy"] == pytest.approx(33 / 37)
    assert m["fabricated_values"] == 0
