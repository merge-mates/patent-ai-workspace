"""의견서 코드 검사 (P2, 모델 없이): 종속항 처리 일치율·보정 항 언급률·심사관 위치 인용률.

기대값은 11/26 지시문 6절 "종속항 처리 일치율" 표에서 가져왔다. 글자는 만든 문장 (OA 원문 아님).
"""

from eval.opinion.checks import (
    DraftText,
    amended_mention_rate,
    draft_treatment,
    examiner_location_hit,
    paragraph_numbers,
    treatment_agreement,
)
from eval.opinion.text import bundle_covers, mentioned_claims

AMEND = (
    "청구항 제3항을 삭제하고, 제4항의 구성을 제1항에 부가하였습니다. "
    "제5항은 인용항을 정정하였습니다."
)
RESP = "보정된 청구항 1은 인용발명 1과 다릅니다. 청구항 1을 인용하는 종속항 역시 진보성이 있습니다."


def draft(amendment=AMEND, response=RESP):
    return DraftText(amendment=amendment, response=response)


def test_청구항_번호를_목록과_범위로_읽는다():
    assert mentioned_claims("제1항, 제3-5항 및 청구항 7") == {1, 3, 4, 5, 7}
    assert mentioned_claims("1, 11-13, 20항을 수정") == {1, 11, 12, 13, 20}
    assert mentioned_claims("청구항 제1항 내지 제4항") == {1, 2, 3, 4}


def test_초안_처리는_보정_설명의_말로_가른다():
    d = draft()
    assert draft_treatment(3, d) == "삭제"
    assert draft_treatment(4, d) == "합침"
    assert draft_treatment(5, d) == "자체 보정"
    assert draft_treatment(2, d) == "묶음 처리"  # 번호 없는 '종속항 역시' 문장


def test_묶음_문장이_없으면_언급_없음():
    d = draft(amendment="", response="보정된 청구항 1은 인용발명과 다릅니다.")
    assert draft_treatment(2, d) == "언급 없음"


def test_띄어쓰기로_끊긴_묶음_문장도_잡는다():
    assert bundle_covers("청구항 제8항을 인 용하는 청구항 제9항도 진보성이 인정됩니다", 9)
    assert not bundle_covers("청구항 제8항을 인 용하는 청구항 제9항도 진보성이 인정됩니다", 4)


def test_일치율은_처리_논점마다_같으면_1():
    issues = [
        {"claim": 3, "role": "처리", "actual": "삭제"},
        {"claim": 4, "role": "처리", "actual": "합침"},
        {"claim": 2, "role": "처리", "actual": "언급 없음"},
        {"claim": 1, "role": "반박", "actual": "반박"},  # 반박 논점은 세지 않음
    ]
    hits, total, rows = treatment_agreement(issues, draft())
    assert (hits, total) == (2, 3)
    assert [r["draft"] for r in rows] == ["삭제", "합침", "묶음 처리"]


def test_보정_항_언급률():
    assert amended_mention_rate([3, 4, 9, 10], draft()) == (2, 4)  # 3·4만 보정 설명에 번호
    assert amended_mention_rate([], draft()) == (0, 0)


def test_문단_번호는_여러_꼴로_읽는다():
    assert paragraph_numbers("[0022]-[0025]") == {22, 23, 24, 25}
    assert paragraph_numbers("인용발명 1의 【0058】 및 식별번호 [0060]") == {58, 60}
    assert paragraph_numbers("도 3") == set()


def test_심사관_위치는_초안이_그_문단_하나라도_짚으면_맞음():
    loc = {"D1": ["[0021]", "[0022]-[0025]", "도 2"]}
    assert examiner_location_hit(loc, "인용발명 1의 [0024]에는 X가 없습니다")
    assert not examiner_location_hit(loc, "인용발명 1은 X가 없습니다")
    assert (
        examiner_location_hit({"D1": ["도 2"]}, "인용발명 1의 도 2") is None
    )  # 문단 위치 없음 = 셈 밖


def test_줄마다_따로인_표는_줄을_마디로_본다():
    d = draft(amendment="[보정 결과 표]\n- 제12항: 보정\n- 제15항: 삭제", response="")
    assert draft_treatment(12, d) == "자체 보정"
    assert draft_treatment(15, d) == "삭제"


def test_보정하지_않았다는_말은_자체_보정이_아니다():
    d = draft(
        amendment="청구항 1을 한정하였습니다. 청구항 2 내지 4는 보정하지 않았습니다.",
        response="청구항 1을 인용하는 종속항 역시 진보성이 있습니다.",
    )
    assert draft_treatment(3, d) == "묶음 처리"
    d2 = draft(amendment="제5항은 그대로 두었습니다.", response="")
    assert draft_treatment(5, d2) == "언급 없음"
