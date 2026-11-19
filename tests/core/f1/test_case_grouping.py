"""사건 자료 묶기 규칙 테스트 (#16). 번호는 모두 지어낸 것 (2099년 값, 실제 사건 아님)."""

import pytest

from patent_ai.core.f1_oa_reader.case_grouping import (
    HistoryEvent,
    MaterialInput,
    group_materials,
    normalize_receipt_number,
    read_number,
    select_examined_version,
)
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason

# --- T1 번호 읽기·정규화 -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "1-1-2099-0000001-12",  # 하이픈 있음
        "112099000000112",  # 하이픈 없음
        "접수번호: 1-1-2099-0000001-12 ",  # 이름표·공백이 붙음
    ],
)
def test_number_접수번호_꼴이면_숫자_15자리(text):
    assert normalize_receipt_number(text) == "112099000000112"


@pytest.mark.parametrize(
    "text",
    [
        "",  # 빈 글자
        "1-1-2099-0000001",  # 끝 두 자리 없음
        "1-1-2099-000001-12",  # 가운데 자리 수 모자람
        "1-1-2099-0000001-123",  # 끝 자리 수 넘침
        "21-1-2099-0000001-12",  # 앞에 숫자가 더 붙음
        "9-5-2099-012345678",  # 발송번호 꼴
        "10-2099-0001234",  # 출원번호 꼴
    ],
)
def test_number_접수번호_꼴이_아니면_None(text):
    assert normalize_receipt_number(text) is None


@pytest.mark.parametrize(
    ("kind", "text", "value"),
    [
        ("application", "10-2099-0001234", "1020990001234"),
        ("dispatch", "9-5-2099-012345678", "952099012345678"),
        ("receipt", "1-1-2099-0000001-12", "112099000000112"),
    ],
)
def test_number_읽으면_confirmed_원문_글자_그대로(kind, text, value):
    v = read_number(kind, text)
    assert v.value == value
    assert v.raw_text == text  # 원문 글자는 정규화하지 않고 그대로
    assert v.status.value == StatusValue.CONFIRMED


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("application", "10-2099-001234"),  # 자리 수 틀림
        ("dispatch", "1-1-2099-0000001-12"),  # 접수번호를 발송번호 칸에
        ("receipt", "9-5-2099-012345678"),  # 발송번호를 접수번호 칸에
    ],
)
def test_number_못_읽으면_unverified_값_없음_글자는_남김(kind, text):
    v = read_number(kind, text)
    assert v.value is None
    assert v.raw_text == text  # 사람이 볼 수 있게 글자는 남긴다
    assert v.status.value == StatusValue.UNVERIFIED
    assert v.status.reason == UnverifiedReason.NOT_EXTRACTED


@pytest.mark.parametrize("text", [None, "", "   "])
def test_number_번호_글자가_없으면_unverified_글자도_없음(text):
    v = read_number("application", text)
    assert v.value is None
    assert v.raw_text is None
    assert v.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_number_번호가_둘_이상_섞이면_ambiguous():
    v = read_number("receipt", "접수 1-1-2099-0000001-12, 1-1-2099-0000002-34")
    assert v.value is None
    assert v.status.reason == UnverifiedReason.AMBIGUOUS


def test_number_같은_번호가_두_번이면_하나로_봄():
    v = read_number("receipt", "1-1-2099-0000001-12 (1-1-2099-0000001-12)")
    assert v.value == "112099000000112"


# --- T2 같은 사건·같은 문서로 묶기 -----------------------------------------------

CASE = "1020990001234"  # 사건 출원번호 (정규화한 값)
APP = "10-2099-0001234"


def _m(doc_id, kind, app=APP, number=None, source="uploaded", date=None):
    return MaterialInput(
        document_id=doc_id,
        kind=kind,
        source=source,
        application_number_text=app,
        doc_number_text=number,
        date_text=date,
    )


def _by_id(grouped):
    return {g.document_id: g for g in grouped}


def test_group_같은_출원번호면_OA는_발송번호_보정서는_접수번호_열쇠():
    out = _by_id(
        group_materials(
            [
                _m("d_oa1", "oa", number="9-5-2099-012345678"),
                _m("d_amd1", "amendment", number="1-1-2099-0000001-12"),
                _m("d_cit1", "citation", app=None, source="api"),
                _m("d_clm0", "claims", source="api"),
            ],
            CASE,
        )
    )
    # 확인된 이력 사건(OA·보정서)만 열쇠를 갖고, 서로 다른 문서는 열쇠가 다르다
    assert out["d_oa1"].key is not None
    assert out["d_amd1"].key is not None
    assert out["d_oa1"].key != out["d_amd1"].key
    assert all(g.status.value == StatusValue.CONFIRMED for g in out.values())
    # 인용문헌은 다른 출원의 문서라 출원번호로 묶지 않는다 (OA 연결은 T4)
    assert out["d_cit1"].key is None
    assert out["d_cit1"].application_number is None
    # 청구항은 출원번호만 본다 (판 연결은 #54)
    assert out["d_clm0"].key is None
    assert out["d_clm0"].application_number.value == CASE


def test_group_같은_문서를_두_번_받으면_같은_열쇠():
    # 자동 조회로 받은 OA와 사용자가 올린 OA가 같은 발송번호 → 같은 문서로 묶임
    out = group_materials(
        [
            _m("d_api", "oa", number="9-5-2099-012345678", source="api"),
            _m("d_up", "oa", number="952099012345678", source="uploaded"),
        ],
        CASE,
    )
    assert len({g.key for g in out}) == 1
    assert out[0].key is not None
    assert all(g.status.value == StatusValue.CONFIRMED for g in out)


def test_group_빈_목록이면_빈_결과와_경고(caplog):
    assert group_materials([], CASE) == []
    assert "자료가 없음" in caplog.text


def test_group_다른_출원번호면_conflict_열쇠_없음():
    (g,) = group_materials(
        [_m("d_x", "oa", app="10-2099-0009999", number="9-5-2099-012345678")], CASE
    )
    assert g.status.value == StatusValue.CONFLICT
    assert g.key is None


@pytest.mark.parametrize(
    ("app", "number", "reason"),
    [
        (None, "9-5-2099-012345678", UnverifiedReason.NOT_EXTRACTED),  # 출원번호 없음
        ("10-2099-01234", "9-5-2099-012345678", UnverifiedReason.NOT_EXTRACTED),  # 출원번호 꼴 틀림
        (APP, None, UnverifiedReason.NOT_EXTRACTED),  # 발송번호 없음
        (APP, "9-5-2099-0123", UnverifiedReason.NOT_EXTRACTED),  # 발송번호 꼴 틀림
        (APP, "9-5-2099-012345678, 9-5-2099-087654321", UnverifiedReason.AMBIGUOUS),
    ],
)
def test_group_번호를_못_읽으면_unverified_열쇠_없음(app, number, reason):
    (g,) = group_materials([_m("d_oa", "oa", app=app, number=number)], CASE)
    assert g.status.value == StatusValue.UNVERIFIED
    assert g.status.reason == reason
    assert g.key is None


def test_group_다른_출원번호가_못_읽은_번호보다_나쁨():
    (g,) = group_materials([_m("d_x", "oa", app="10-2099-0009999", number=None)], CASE)
    assert g.status.value == StatusValue.CONFLICT


def test_group_같은_접수번호인데_종류가_다르면_둘_다_conflict():
    out = group_materials(
        [
            _m("d_amd", "amendment", number="1-1-2099-0000001-12"),
            _m("d_opn", "opinion", number="1-1-2099-0000001-12"),
            _m("d_oa", "oa", number="9-5-2099-012345678"),
        ],
        CASE,
    )
    st = {g.document_id: g.status.value for g in out}
    assert st == {
        "d_amd": StatusValue.CONFLICT,
        "d_opn": StatusValue.CONFLICT,
        "d_oa": StatusValue.CONFIRMED,
    }
    keys = {g.document_id: g.key for g in out}
    assert keys["d_amd"] is None and keys["d_opn"] is None
    assert keys["d_oa"] is not None


def test_group_날짜가_같아도_번호가_다르면_따로():
    out = group_materials(
        [
            _m("d_a", "amendment", number="1-1-2099-0000001-12", date="2099.02.01."),
            _m("d_b", "amendment", number="1-1-2099-0000002-34", date="2099.02.01."),
        ],
        CASE,
    )
    assert len({g.key for g in out}) == 2


def test_group_날짜만_있고_번호가_없으면_묶지_않음():
    (g,) = group_materials([_m("d_a", "amendment", number=None, date="2099.02.01.")], CASE)
    assert g.key is None
    assert g.status.value == StatusValue.UNVERIFIED


def test_group_모르는_종류는_입력에서_거부():
    with pytest.raises(ValueError):
        _m("d", "something")


def test_number_하이픈으로_이어_붙은_번호_둘도_ambiguous():
    v = read_number("receipt", "1-1-2099-0000001-12-1-1-2099-0000002-34")
    assert v.value is None
    assert v.status.reason == UnverifiedReason.AMBIGUOUS


def test_group_인용문헌은_다른_출원번호가_적혀도_confirmed():
    (g,) = group_materials([_m("d_cit", "citation", app="10-2099-0009999")], CASE)
    assert g.status.value == StatusValue.CONFIRMED
    assert g.key is None


@pytest.mark.parametrize("kind", ["claims", "spec"])
@pytest.mark.parametrize(
    ("app", "expected"),
    [("10-2099-0009999", StatusValue.CONFLICT), (None, StatusValue.UNVERIFIED)],
)
def test_group_청구항_명세서는_출원번호를_본다(kind, app, expected):
    (g,) = group_materials([_m("d", kind, app=app)], CASE)
    assert g.status.value == expected
    assert g.key is None


def test_group_사건_출원번호는_하이픈이_있어도_맞춤():
    (g,) = group_materials([_m("d_oa", "oa", number="9-5-2099-012345678")], APP)
    assert g.status.value == StatusValue.CONFIRMED


@pytest.mark.parametrize("case_number", ["", "10-2099-01234"])
def test_group_사건_출원번호_꼴이_아니면_ValueError(case_number):
    with pytest.raises(ValueError):
        group_materials([_m("d_oa", "oa", number="9-5-2099-012345678")], case_number)


# --- T3 심사 대상 판 고르기 -----------------------------------------------------

OA1 = "9-5-2099-000000001"
OA2 = "9-5-2099-000000002"
AMD1 = "1-1-2099-0000001-12"
AMD2 = "1-1-2099-0000002-34"


def _h(kind, number):
    return HistoryEvent(kind=kind, number_text=number)


# 이력 순서(#54가 정함): OA ① → 보정서 → OA ②
TWO_OAS = [_h("oa", OA1), _h("amendment", AMD1), _h("oa", OA2)]


def test_version_첫_OA는_출원_때_판_v0():
    v = select_examined_version(TWO_OAS, OA1)
    assert v.value == "v0"
    assert v.status.value == StatusValue.CONFIRMED


def test_version_두번째_OA는_앞_보정서_접수번호():
    v = select_examined_version(TWO_OAS, OA2)
    assert v.value == "112099000000112"
    assert v.raw_text == AMD1
    assert v.status.value == StatusValue.CONFIRMED


def test_version_보정서가_여럿이면_대상_OA_바로_앞_마지막():
    hist = [_h("oa", OA1), _h("amendment", AMD1), _h("amendment", AMD2), _h("oa", OA2)]
    assert select_examined_version(hist, OA2).value == "112099000000234"


def test_version_대상_OA_뒤_보정서는_보지_않음():
    hist = [_h("oa", OA1), _h("amendment", AMD1)]
    assert select_examined_version(hist, OA1).value == "v0"


def test_version_의견서만_있으면_판은_그대로_v0():
    hist = [_h("oa", OA1), _h("opinion", AMD1), _h("oa", OA2)]
    assert select_examined_version(hist, OA2).value == "v0"


def test_version_대상_발송번호는_하이픈_없어도_됨():
    assert select_examined_version(TWO_OAS, "952099000000002").value == "112099000000112"


def test_version_이력을_못_가져오면_lookup_failed():
    v = select_examined_version(None, OA1)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.LOOKUP_FAILED


def test_version_빈_이력이면_lookup_failed와_경고(caplog):
    v = select_examined_version([], OA1)
    assert v.status.reason == UnverifiedReason.LOOKUP_FAILED
    assert "이력이 비어 있음" in caplog.text


def test_version_대상_OA가_이력에_없으면_lookup_failed():
    v = select_examined_version([_h("oa", OA1)], OA2)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.LOOKUP_FAILED


def test_version_대상_OA가_이력에_두_번이면_ambiguous():
    hist = [_h("oa", OA1), _h("amendment", AMD1), _h("oa", OA1)]
    v = select_examined_version(hist, OA1)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.AMBIGUOUS


@pytest.mark.parametrize("target", [None, "", "9-5-2099-0001"])
def test_version_대상_발송번호를_못_읽으면_input_unverified(target):
    v = select_examined_version(TWO_OAS, target)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.INPUT_UNVERIFIED


def test_version_마지막_보정서_번호를_못_읽으면_not_extracted():
    hist = [_h("oa", OA1), _h("amendment", AMD1), _h("amendment", "1-1-2099-12"), _h("oa", OA2)]
    v = select_examined_version(hist, OA2)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_version_앞쪽_보정서만_못_읽고_마지막이_읽히면_마지막():
    hist = [_h("amendment", "1-1-2099-12"), _h("oa", OA1), _h("amendment", AMD2), _h("oa", OA2)]
    assert select_examined_version(hist, OA2).value == "112099000000234"


def test_version_대상을_못_찾았는데_번호_없는_OA가_있으면_not_extracted():
    hist = [_h("oa", OA1), _h("amendment", AMD1), _h("oa", None)]
    v = select_examined_version(hist, OA2)
    assert v.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_version_마지막_보정서에_번호가_둘이면_ambiguous():
    hist = [_h("oa", OA1), _h("amendment", f"{AMD1}, {AMD2}"), _h("oa", OA2)]
    v = select_examined_version(hist, OA2)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.AMBIGUOUS
