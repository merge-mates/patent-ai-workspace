"""판 문서 글자 → 청구항 번호별 원문 (이슈 #205 T1). 모델 호출 없는 코드 도구."""

from patent_ai.core.cases.claim_texts import claim_region, claims_at_version
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason

# 출원서(출원 때 판) 글자 모양: 실제 PDF 글자 층과 같은 머리 줄
APPLICATION = (
    "【발명의 설명】\n【0001】 화분에 관한 것이다.\n"
    "【청구범위】\n【청구항 1】\n물통을 포함하는\n화분.\n"
    "【청구항 2】\n제1항에 있어서, 받침을 더 포함하는 화분.\n"
    "【청구항 3】\n제1 항에 있어서, 뚜껑을 더 포함하는 화분.\n"
    "【요약서】\n【요약】\n화분이 개시된다.\n【대표도】\n도1"
)

# 보정서 글자 모양: 표지의 "별지와 같음" 뒤에 바꾼 항목만 나온다
AMENDMENT = (
    "【보정할 사항】\n【보정대상항목】 별지와 같음\n【보정방법】 별지와 같음\n"
    "【보정내용】 별지와 같음\n【취지】\n위와 같이 제출합니다.\n보정서\n"
    "【보정대상항목】 청구항 1\n【보정방법】 정정\n【보정내용】\n"
    "【청구항 1】\n물통과 센서를 포함하는 화분.\n"
    "【보정대상항목】 청구항 3\n【보정방법】 삭제\n"
    "【보정대상항목】 식별번호 0001\n【보정방법】 정정\n【보정내용】\n"
    "【0001】 센서 화분에 관한 것이다.\n"
    "【보정대상항목】 청구항 4\n【보정방법】 추가\n【보정내용】\n"
    "【청구항 4】\n제1항에 있어서, 바퀴를 더 포함하는 화분."
)


def test_claim_texts_출원서에서_청구항_번호별_원문을_뽑는다():
    got = claims_at_version([APPLICATION])
    assert got.status.value == StatusValue.CONFIRMED
    assert got.claims == {
        1: "물통을 포함하는\n화분.",
        2: "제1항에 있어서, 받침을 더 포함하는 화분.",
        3: "제1 항에 있어서, 뚜껑을 더 포함하는 화분.",
    }


def test_claim_texts_요약서와_발명의_설명은_청구항에_붙지_않는다():
    got = claims_at_version([APPLICATION])
    assert all("요약" not in t and "【" not in t for t in got.claims.values())


def test_claim_texts_쪽이_바뀌어도_청구항이_이어진다():
    # 부르는 쪽이 쪽 글자를 줄바꿈으로 이어 붙여 넘긴다
    pages = ["【청구범위】\n【청구항 1】\n물통을", "포함하는 화분.\n【요약서】"]
    got = claims_at_version(["\n".join(pages)])
    assert got.claims == {1: "물통을\n포함하는 화분."}


def test_claim_texts_보정서는_앞_판에_정정_삭제_추가를_적용한다():
    got = claims_at_version([APPLICATION, AMENDMENT])
    assert got.status.value == StatusValue.CONFIRMED
    assert got.claims == {
        1: "물통과 센서를 포함하는 화분.",
        2: "제1항에 있어서, 받침을 더 포함하는 화분.",
        4: "제1항에 있어서, 바퀴를 더 포함하는 화분.",
    }


def test_claim_texts_보정서가_청구범위_전체를_바꾸면_새_청구항_묶음이_된다():
    whole = (
        "보정서\n【보정대상항목】 청구범위\n【보정방법】 정정\n【보정내용】\n"
        "【청구범위】\n【청구항 1】\n새 화분."
    )
    got = claims_at_version([APPLICATION, whole])
    assert got.status.value == StatusValue.CONFIRMED
    assert got.claims == {1: "새 화분."}


def test_claim_texts_보정서가_여러_번이면_차례로_적용한다():
    second = (
        "【보정대상항목】 청구항 2\n【보정방법】 정정\n【보정내용】\n"
        "【청구항 2】\n제1항에 있어서, 둥근 받침을 더 포함하는 화분."
    )
    got = claims_at_version([APPLICATION, AMENDMENT, second])
    assert got.claims[1] == "물통과 센서를 포함하는 화분."
    assert got.claims[2] == "제1항에 있어서, 둥근 받침을 더 포함하는 화분."


def test_claim_texts_삭제라고만_적힌_청구항은_뺀다():
    text = "【청구범위】\n【청구항 1】\n화분.\n【청구항 2】\n삭제\n【청구항 3】\n제1항의 화분."
    got = claims_at_version([text])
    assert got.status.value == StatusValue.CONFIRMED
    assert got.claims == {1: "화분.", 3: "제1항의 화분."}


def test_claim_texts_번호가_겹치면_지어내지_않고_unverified():
    text = "【청구범위】\n【청구항 1】\n화분.\n【청구항 1】\n다른 화분."
    got = claims_at_version([text])
    assert got.status.value == StatusValue.UNVERIFIED
    assert got.status.reason == UnverifiedReason.AMBIGUOUS


def test_claim_texts_번호가_빠지면_unverified():
    text = "【청구범위】\n【청구항 1】\n화분.\n【청구항 3】\n제1항의 화분."
    got = claims_at_version([text])
    assert got.status.value == StatusValue.UNVERIFIED
    assert got.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_claim_texts_청구항이_하나도_없으면_unverified():
    got = claims_at_version(["【발명의 설명】\n【0001】 화분."])
    assert got.status.value == StatusValue.UNVERIFIED
    assert got.claims == {}


def test_claim_texts_빈_청구항_글이면_unverified():
    got = claims_at_version(["【청구범위】\n【청구항 1】\n\n【청구항 2】\n화분."])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_보정서에_청구항_항목이_없으면_unverified():
    # 판이 보정서로 생겼는데 청구항을 하나도 못 읽으면 앞 판을 그대로 쓰지 않는다
    spec_only = "【보정대상항목】 식별번호 0001\n【보정방법】 정정\n【보정내용】\n【0001】 화분."
    got = claims_at_version([APPLICATION, spec_only])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_정정_항목의_번호와_내용_번호가_다르면_unverified():
    wrong = "【보정대상항목】 청구항 1\n【보정방법】 정정\n【보정내용】\n【청구항 2】\n화분."
    got = claims_at_version([APPLICATION, wrong])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_없는_청구항을_삭제하면_unverified():
    wrong = "【보정대상항목】 청구항 9\n【보정방법】 삭제"
    got = claims_at_version([APPLICATION, wrong])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_모르는_보정방법이면_unverified():
    wrong = "【보정대상항목】 청구항 1\n【보정방법】 이상한방법\n【보정내용】\n【청구항 1】\n화분."
    got = claims_at_version([APPLICATION, wrong])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_판_문서가_없으면_unverified():
    got = claims_at_version([])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_이미_있는_청구항을_추가하면_unverified():
    # 덮어쓰지 않는다 (리뷰 #215)
    wrong = "【보정대상항목】 청구항 2\n【보정방법】 추가\n【보정내용】\n【청구항 2】\n새 화분."
    got = claims_at_version([APPLICATION, wrong])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_없는_청구항을_정정하면_unverified():
    # 번호가 빈 채 새 항이 생기지 않게 한다 (리뷰 #215)
    wrong = "【보정대상항목】 청구항 7\n【보정방법】 정정\n【보정내용】\n【청구항 7】\n새 화분."
    got = claims_at_version([APPLICATION, wrong])
    assert got.status.value == StatusValue.UNVERIFIED


def test_claim_texts_보정서_끝_첨부서류는_마지막_청구항에_붙지_않는다():
    tail = AMENDMENT + "\n【첨부서류】 1. 위임장 1통"
    got = claims_at_version([APPLICATION, tail])
    assert got.claims[4] == "제1항에 있어서, 바퀴를 더 포함하는 화분."


def test_claim_region_출원서는_청구범위_구간이다():
    begin, end = claim_region(APPLICATION, first=True)
    assert APPLICATION[begin:end].strip().startswith("【청구항 1】")
    assert "요약" not in APPLICATION[begin:end]


def test_claim_region_보정서는_첫_청구항_항목부터_마지막_청구항_항목까지():
    begin, end = claim_region(AMENDMENT, first=False)
    assert AMENDMENT[begin:].startswith("【보정대상항목】 청구항 1")
    assert AMENDMENT[begin:end].endswith("바퀴를 더 포함하는 화분.")
    assert "별지와 같음" not in AMENDMENT[begin:end]


def test_claim_region_청구항이_없으면_None():
    assert claim_region("【발명의 설명】\n【0001】 화분.", first=True) is None
