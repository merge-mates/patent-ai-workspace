"""OAResult -> 정답 꼴 예측 (eval/f1/adapt.py). 확인됨 값만 '냈다'로 본다 (#20 task 5 결정)."""

import json
from pathlib import Path

import pytest
from f1_oa_builder import AMBIGUOUS, ev

from eval.f1.adapt import to_pred
from eval.f1.config import F1EvalConfig
from eval.f1.gold import F1Gold
from eval.f1.score import oa_key, score_f1
from patent_ai.core.schemas.common import (
    Candidate,
    ExtractedValue,
    Status,
    StatusValue,
    UnverifiedReason,
)

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


def test_확인되지_않은_보정_참고사항은_안_낸_칸으로(make_oa):
    from patent_ai.core.schemas.oa_result import ExaminerHints

    hints = ExaminerHints(allowable_claims=ev([]), amendment_note=ev(None, status=AMBIGUOUS))
    oa = make_oa(examiner_hints=hints)
    p = to_pred(oa)
    assert p.amendment_note.given is False
    # 정답이 '없음'이어도 맞음으로 세지 않는다
    assert _score(oa)["metrics"]["field_accuracy"] == pytest.approx(36 / 37)


def test_같은_라벨이_여러_거절이유에_있으면_확인된_키를_쓴다(make_oa):
    from f1_oa_builder import D1, _citation

    oa = make_oa()
    r1, r2, r3 = oa.rejections
    unsure = _citation(*D1).model_copy(update={"number": ev("KR20990000001A", D1[2], 2, AMBIGUOUS)})
    r1 = r1.model_copy(update={"citations": [unsure, r1.citations[1]]})
    r2 = r2.model_copy(update={"citations": [_citation(*D1)]})
    p = to_pred(oa.model_copy(update={"rejections": [r1, r2, r3]}))
    d1 = next(c for c in p.citations if c.label == "D1")
    assert d1.key == "KR20990000001A"
    assert d1.page == 2
    assert d1.rejections == [1, 2]


def test_확인된_칸이_없는_정답_밖_거절이유는_지어낸_값이_아니다(make_oa):
    # 앱이 원문 대조에 떨어뜨려 '확인되지 않음'으로 낸 줄은 지어낸 것이 아니다 (#119 재아 리뷰)
    from patent_ai.core.schemas.oa_result import build_rejection

    oa = make_oa()
    extra = build_rejection(
        document_id="doc-1",
        no=4,
        article=ev("29-2", "특허법 제29조제2항", 1, AMBIGUOUS),
        supported=True,
        claims=ev([1], "청구항 제1항", 1, AMBIGUOUS),
        citations=[],
        examiner_reasoning=ev(None, status=AMBIGUOUS),
    )
    oa = oa.model_copy(update={"rejections": [*oa.rejections, extra]})
    assert _score(oa)["metrics"]["fabricated_values"] == 0


def test_확인된_번호가_없는_정답_밖_인용은_지어낸_값이_아니다(make_oa):
    from patent_ai.core.schemas.oa_result import Citation

    oa = make_oa()
    r1 = oa.rejections[0]
    d3 = Citation(
        label="D3",
        number=ev("KR20990000003A", "공개특허공보 제10-2099-0000003호", 2, AMBIGUOUS),
        country=ev("KR"),
        country_supported=True,
        cited_paragraphs=ev([]),
    )
    r1 = r1.model_copy(update={"citations": [*r1.citations, d3]})
    oa = oa.model_copy(update={"rejections": [r1, *oa.rejections[1:]]})
    assert _score(oa)["metrics"]["fabricated_values"] == 0


def test_같은_라벨에_확인된_번호가_둘이면_경고(make_oa, caplog):
    import logging

    from f1_oa_builder import D1, _citation

    oa = make_oa()
    r1, r2, r3 = oa.rejections
    other = _citation(*D1).model_copy(update={"number": ev("KR20990000009A", "다른 번호", 2)})
    r2 = r2.model_copy(update={"citations": [other]})
    with caplog.at_level(logging.WARNING):
        p = to_pred(oa.model_copy(update={"rejections": [r1, r2, r3]}))
    assert next(c for c in p.citations if c.label == "D1").key == "KR20990000001A"
    assert "D1" in caplog.text
    assert "KR20990000009A" not in caplog.text  # 번호 글자는 남기지 않는다


def test_대조에_떨어져_모델_값만_남은_청구항_줄은_채점에_넣지_않는다(make_oa):
    # D3(11/26): unverified 줄에 모델 값이 남아도 F1 점수에는 확인된 줄만 들어간다
    oa = make_oa()
    first = oa.claim_rows[0]
    failed = first.model_copy(
        update={
            "status": Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
            "check_failed": "위치 글자를 원문 쪽에서 못 찾음",
        }
    )
    p = to_pred(oa.model_copy(update={"claim_rows": [failed, *oa.claim_rows[1:]]}))
    assert (first.claim, first.rejection) not in {(r.claim, r.rejection) for r in p.claim_rows}
