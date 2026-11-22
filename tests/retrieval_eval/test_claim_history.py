"""OA 당시 청구항 복원 (design 3-1). 지어낸 청구항이력·행정이력만 쓴다."""

from pathlib import Path

import pytest

from eval.retrieval.claim_history import (
    OaNotFound,
    claims_at_oa,
    claims_at_oa_with_stats,
    expand_claims,
)

OA = "9-5-2099-0000002"
# 입력 폴더 꼴 <출원번호>/<발송번호>/ (#159). 이 픽스처 이력은 일부러 OA 뒤 줄까지 둔다
CASE = Path(__file__).parent.parent / "fixtures" / "cite_search" / "cases" / "10-2099-0000001" / OA
HIST = CASE / "10-2099-0000001_청구항이력.txt"
ADMIN = CASE / "10-2099-0000001_행정이력.txt"


def test_expand_claims_범위와_낱개를_펼친다():
    assert expand_claims("3-4,8") == [3, 4, 8]
    assert expand_claims("11-13,17") == [11, 12, 13, 17]
    assert expand_claims("5") == [5]


def test_expand_claims_거꾸로_범위나_글자는_오류():
    with pytest.raises(ValueError):
        expand_claims("5-3")
    with pytest.raises(ValueError):
        expand_claims("가")


def test_OA_앞_접수의_신규_수정_삭제만_차례로_적용한다():
    claims = claims_at_oa(HIST, ADMIN, OA)
    # 출원서 신규 6개 - 보정서(OA 앞)의 5항 삭제 = 5개
    assert sorted(claims) == [1, 2, 3, 4, 6]
    # 3항은 OA 앞 보정서로 수정됨
    assert claims[3] == "세번째 청구항 OA 전 보정 글자."
    # OA 뒤 의견서/보정서의 수정은 안 들어감
    assert "OA 뒤" not in claims[1]
    assert claims[2] == "제1항에 있어서 두번째 청구항 처음 글자."


def test_br은_줄바꿈이_된다():
    assert claims_at_oa(HIST, ADMIN, OA)[1].endswith("방법.\n추가 줄 하나.")


def test_행정이력에_없는_접수의_변경은_적용하지_않고_센다():
    claims, unmatched, unknown = claims_at_oa_with_stats(HIST, ADMIN, OA)
    assert "행정이력에 없는" not in claims[4]
    assert unmatched == 1
    assert unknown == 0


def test_OA_발송번호가_행정이력에_없으면_OaNotFound():
    with pytest.raises(OaNotFound):
        claims_at_oa(HIST, ADMIN, "9-5-2099-9999999")


def test_날짜가_아니라_행정이력_줄_순서로_자른다(tmp_path):
    # 보정서 줄이 OA 줄 앞에 있으면 날짜가 OA보다 늦어도 적용, 뒤에 있으면 날짜가 빨라도 안 함
    admin = tmp_path / "a.txt"
    admin.write_text(
        "출원번호¶접수발송번호¶접수발송일자¶접수발송서류명¶접수발송서류영문명¶처리상태¶처리상태영문명¶단계¶심판번호¶등록번호\n"
        "X¶R1¶20990101¶특허출원서¶¶¶¶¶¶\n"
        "X¶R2¶20991231¶보정서¶¶¶¶¶¶\n"
        "X¶OA1¶20990601¶의견제출통지서¶¶¶¶¶¶\n"
        "X¶R3¶20990102¶보정서¶¶¶¶¶¶\n",
        encoding="utf-8",
    )
    hist = tmp_path / "h.txt"
    hist.write_text(
        "출원번호¶접수발송일련번호¶접수발송번호¶청구항번호¶변경구분코드¶변경구분명¶청구항¶변동대상접수문서번호¶변동청구항\n"
        "X¶1¶R1¶1¶N¶신규¶처음¶¶\n"
        "X¶2¶R2¶1¶U¶수정¶날짜는 늦은 앞 보정¶¶\n"
        "X¶3¶R3¶1¶U¶수정¶날짜는 빠른 뒤 보정¶¶\n",
        encoding="utf-8",
    )
    assert claims_at_oa(hist, admin, "OA1") == {1: "날짜는 늦은 앞 보정"}


def test_모르는_변경구분명은_건너뛰고_센다(tmp_path):
    # 리뷰 요청 3: 신규·수정·삭제가 아닌 값은 조용히 넘기지 않고 건수를 돌려준다
    admin = tmp_path / "a.txt"
    admin.write_text(
        "출원번호¶접수발송번호¶접수발송일자¶접수발송서류명¶접수발송서류영문명¶처리상태¶처리상태영문명¶단계¶심판번호¶등록번호\n"
        "X¶R1¶20990101¶특허출원서¶¶¶¶¶¶\n"
        "X¶R2¶20990201¶보정서¶¶¶¶¶¶\n"
        "X¶OA1¶20990601¶의견제출통지서¶¶¶¶¶¶\n",
        encoding="utf-8",
    )
    hist = tmp_path / "h.txt"
    hist.write_text(
        "출원번호¶접수발송일련번호¶접수발송번호¶청구항번호¶변경구분코드¶변경구분명¶청구항¶변동대상접수문서번호¶변동청구항\n"
        "X¶1¶R1¶1¶N¶신규¶처음¶¶\n"
        "X¶2¶R2¶1¶Z¶지어낸종류¶바뀌면 안 됨¶¶\n",
        encoding="utf-8",
    )
    claims, unmatched, unknown = claims_at_oa_with_stats(hist, admin, "OA1")
    assert claims == {1: "처음"}
    assert unmatched == 0
    assert unknown == 1
