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
    # 2항: 실제 언급 없음 + 초안 묶음 문장 → 맞음 (11/26 재아 결정)
    assert (hits, total) == (3, 3)
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


# ---- P6 초안 쪽 10줄 검사에서 틀린 꼴 (11/26) ----
def test_따옴표_안_청구항_번호는_그_항_언급이_아니다():
    d = draft(
        amendment="청구항 9는 인용하는 항이 '청구항 1 내지 청구항 8 중 어느 한 항'에서 "
        "바뀌었습니다.",
        response="",
    )
    assert draft_treatment(9, d) == "자체 보정"
    assert draft_treatment(7, d) == "언급 없음"


def test_동사_없는_조각은_문장_뒤쪽_말로_정한다():
    d = draft(amendment="제14항, 제16항 및 제2~10항, 제17항은 보정하지 않았습니다.", response="")
    assert draft_treatment(6, d) == "언급 없음"
    d2 = draft(amendment="청구항 4와 5, 청구항 7의 구성은 청구항 1에 합쳤습니다.", response="")
    assert draft_treatment(7, d2) == "합침"


def test_됨으로_끝나는_문장도_나눈다():
    d = draft(
        amendment="청구항 1에 구성이 추가됨. 청구항 2 (삭제): 구성은 청구항 1로 합쳐짐. "
        "청구항 6: 표현을 정정함."
    )
    assert draft_treatment(6, d) == "자체 보정"
    assert draft_treatment(2, d) == "합침"


def test_unchanged라고_쓴_항은_바꾸지_않은_것():
    d = draft(amendment="청구항 2-10, 12는 자료상 unchanged로 정리되어 있습니다.", response="")
    assert draft_treatment(4, d) == "언급 없음"


def test_글자를_지우는_말은_청구항_삭제가_아니다():
    d = draft(amendment="청구항 2에는 그 말이 없으므로 '상기'를 단순 삭제하면 됩니다.", response="")
    assert draft_treatment(2, d) != "삭제"
    d2 = draft(amendment="- 제15항: 삭제\n제3항은 삭제되었습니다.", response="")
    assert (draft_treatment(15, d2), draft_treatment(3, d2)) == ("삭제", "삭제")


def test_여러_항을_나열한_요약보다_그_항만_말한_줄을_따른다():
    d = draft(
        amendment="보정으로 바뀐 항은 제1항, 제11항, 제12항(보정)과 제15항(삭제)이다.\n"
        "- 제12항(보정): 인용항을 정정하였다.",
        response="",
    )
    assert draft_treatment(12, d) == "자체 보정"
    assert draft_treatment(15, d) == "삭제"


def test_변경이_없다는_말은_바꾸지_않은_것():
    d = draft(amendment="청구항 3~7은 보정 결과상 변경이 없습니다.", response="")
    assert draft_treatment(4, d) == "언급 없음"


def test_종속항_N_꼴_번호도_읽고_합친도_합침():
    assert mentioned_claims("종속항 2-10, 12는 함께 주장할 수 있습니다") >= {2, 10, 12}
    d = draft(amendment="이 부분은 보정 전 청구항 4, 5, 7의 구성을 합친 것입니다.", response="")
    assert draft_treatment(5, d) == "합침"


def test_따옴표가_마디를_넘어도_문장째_뺀다():
    d = draft(
        amendment="인용항이 '청구항 1 내지 청구항 8 중 어느 한 항'에서 '청구항 3 내지 청구항 8 중 "
        "어느 한 항'으로 바뀌었습니다.",
        response="",
    )
    assert draft_treatment(4, d) == "언급 없음"


def test_삭제한_항도_다른_마디에서_합쳤다고_하면_합침():
    # 합친 항은 늘 지운 항이기도 하다: 코드가 만든 표 줄 "- 제4항: 삭제"가 합침 설명을 이기지 않는다
    d = draft(
        amendment="- 제4항: 삭제\n- 제7항: 삭제\n- 제11항: 삭제\n"
        "청구항 4, 5, 7의 구성은 청구항 1, 8, 15에 합쳤습니다.",
        response="",
    )
    assert draft_treatment(4, d) == "합침"
    assert draft_treatment(7, d) == "합침"
    assert draft_treatment(11, d) == "삭제"  # 합침 말이 없는 지운 항은 그대로 삭제
    assert draft_treatment(1, d) != "삭제"  # 합친 곳(받는 항)은 삭제가 아니다


def test_항_머리표가_있는_줄은_그_항만_말한_것():
    # "- 청구항 3: 청구항 2에 …" 줄의 청구항 2는 인용 관계일 뿐 2항의 처리가 아니다
    d = draft(
        amendment="- 청구항 2: '전처리 모듈'을 '명령'으로 바꿨습니다.\n"
        "- 청구항 3: 청구항 2에 종속하는 구성은 유지하고, 신경망 구성을 추가했습니다.",
        response="",
    )
    assert draft_treatment(2, d) == "자체 보정"


def test_보정_전후_동일하다는_말은_바꾸지_않은_것():
    d = draft(amendment="- 청구항 9, 10은 보정 전후 동일합니다.", response="")
    assert draft_treatment(9, d) == "언급 없음"


def test_실제가_언급_없음이고_초안이_묶음_문장이면_맞음():
    # 11/26 재아 결정: 실제 의견서가 종속항을 언급하지 않았어도 초안이 독립항 논리를 묶음 문장으로
    # 적용하면 맞은 것으로 센다 (초안이 더 완전한 것을 감점하지 않음)
    issues = [{"claim": 2, "role": "처리", "actual": "언급 없음"}]
    hits, total, rows = treatment_agreement(issues, draft())
    assert (hits, total) == (1, 1)
    assert rows[0]["draft"] == "묶음 처리"


def test_표_줄의_보정_표시는_추가_설명보다_앞선다():
    # 코드가 만든 보정 결과 표 "- 제3항: 보정"이 있으면,
    # 반박 설명의 "청구항 3에 … 추가"를 합침으로 읽지 않는다
    d = draft(
        amendment="- 청구항 3: 청구항 2에 종속하는 구성은 유지하고, 신경망 구성을 추가했습니다.\n"
        "- 제3항: 보정",
        response="",
    )
    assert draft_treatment(3, d) == "자체 보정"
