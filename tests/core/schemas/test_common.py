"""결과 공통 칸 테스트. 기대값은 tasks.md m1-i2-14 task-1과 design.md 3-2절에서 가져왔다."""

import logging

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import (
    Evidence,
    ExtractedValue,
    Flag,
    Origin,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)

# ---------- 평소: 네 값 각각 바른 칸 ----------


def test_status_네_값_각각_바른_칸이면_통과():
    assert Status(value="confirmed", checked="1쪽 글자와 일치").value == StatusValue.CONFIRMED
    assert (
        Status(value="unverified", reason="not_extracted").reason == UnverifiedReason.NOT_EXTRACTED
    )
    assert Status(value="not_found_in_scope", searched_scope="KIPRIS 공개 조회").searched_scope
    assert Status(value="conflict").value == StatusValue.CONFLICT


def test_unverified_이유_여섯_값():
    assert {r.value for r in UnverifiedReason} == {
        "lookup_failed",
        "body_missing",
        "edition_unknown",
        "not_extracted",
        "ambiguous",
        "input_unverified",
    }


def test_status_직렬화는_늘_네_키():
    dumped = Status(value="unverified", reason="ambiguous").model_dump(mode="json")
    assert dumped == {
        "value": "unverified",
        "reason": "ambiguous",
        "checked": None,
        "searched_scope": None,
    }


def test_origin_네_값과_flag_두_값():
    assert {o.value for o in Origin} == {
        "ai_generated",
        "ai_default",
        "human_selected",
        "human_edited",
    }
    assert {f.value for f in Flag} == {"needs_human_judgment", "needs_human_review"}


def test_result_base_기본값과_직렬화():
    base = ResultBase(status=Status(value="unverified", reason="not_extracted"))
    dumped = base.model_dump(mode="json")
    assert dumped["origin"] == "ai_generated"
    assert dumped["needs_recheck"] is False
    assert dumped["recheck_reason"] is None
    assert dumped["flags"] == []
    assert dumped["evidence"] == []
    assert set(dumped["status"]) == {"value", "reason", "checked", "searched_scope"}


def test_evidence_칸():
    ev = Evidence(document_id="d_1", page=2, raw_text="제1항 내지 제4항", checked_on="2026-11-18")
    assert ev.edition is None
    assert ev.model_dump(mode="json")["checked_on"] == "2026-11-18"


# ---------- ExtractedValue ----------


def test_extracted_value_평소():
    v = ExtractedValue[str](
        value="10-2099-0000001",
        raw_text="10-2099-0000001",
        page=1,
        status=Status(value="confirmed", checked="1쪽 출원번호 칸 글자와 일치"),
    )
    assert v.candidates == []


def test_extracted_value_날짜는_value_없이_raw_text만():
    v = ExtractedValue[str](
        value=None,
        raw_text="2099.01.26",
        page=1,
        status=Status(value="confirmed", checked="원문 글자만, 날짜 확정 안 함"),
    )
    assert v.value is None and v.raw_text == "2099.01.26"


def test_extracted_value_conflict_후보_둘_value는_null():
    v = ExtractedValue[str](
        value=None,
        status=Status(value="conflict"),
        candidates=[
            {"value": "A", "raw_text": "A", "page": 1, "source": "rule"},
            {"value": "B", "raw_text": "B", "page": 1, "source": "model"},
        ],
    )
    assert [c.source for c in v.candidates] == ["rule", "model"]


def test_extracted_value_conflict인데_value가_있으면_거부():
    with pytest.raises(ValidationError):
        ExtractedValue[str](
            value="A",
            status=Status(value="conflict"),
            candidates=[
                {"value": "A", "source": "rule"},
                {"value": "B", "source": "model"},
            ],
        )


@pytest.mark.parametrize("n", [0, 1])
def test_extracted_value_conflict인데_후보_둘_미만이면_거부(n):
    cands = [{"value": "A", "source": "rule"}][:n]
    with pytest.raises(ValidationError):
        ExtractedValue[str](value=None, status=Status(value="conflict"), candidates=cands)


def test_extracted_value_conflict가_아닌데_후보가_있으면_거부():
    with pytest.raises(ValidationError):
        ExtractedValue[str](
            value="A",
            status=Status(value="confirmed", checked="x"),
            candidates=[
                {"value": "A", "source": "rule"},
                {"value": "B", "source": "model"},
            ],
        )


def test_후보_source는_rule_model만():
    with pytest.raises(ValidationError):
        ExtractedValue[str](
            value=None,
            status=Status(value="conflict"),
            candidates=[
                {"value": "A", "source": "human"},
                {"value": "B", "source": "model"},
            ],
        )


# ---------- 실패: ValidationError ----------


def test_다섯_번째_값은_거부():
    with pytest.raises(ValidationError):
        Status(value="maybe")


def test_unverified인데_이유_없으면_거부():
    with pytest.raises(ValidationError):
        Status(value="unverified")


def test_confirmed인데_checked_없으면_거부():
    with pytest.raises(ValidationError):
        Status(value="confirmed")


def test_not_found_in_scope인데_범위_없으면_거부():
    with pytest.raises(ValidationError):
        Status(value="not_found_in_scope")


def test_맞지_않는_칸은_거부():
    with pytest.raises(ValidationError):
        Status(value="conflict", reason="ambiguous")
    with pytest.raises(ValidationError):
        Status(value="unverified", reason="ambiguous", checked="x")
    with pytest.raises(ValidationError):
        Status(value="confirmed", checked="x", searched_scope="y")


def test_이유_목록_밖_값은_거부():
    with pytest.raises(ValidationError):
        Status(value="unverified", reason="because")


# ---------- worst_status ----------

C = Status(value="confirmed", checked="칸 하나")
N = Status(value="not_found_in_scope", searched_scope="범위 1")
U = Status(value="unverified", reason="lookup_failed")
X = Status(value="conflict")


def test_worst_순서_conflict_unverified_not_found_confirmed():
    assert worst_status([C, N, U, X], "요약").value == StatusValue.CONFLICT
    assert worst_status([C, N, U], "요약").value == StatusValue.UNVERIFIED
    assert worst_status([C, N], "요약").value == StatusValue.NOT_FOUND_IN_SCOPE
    assert worst_status([C, C], "요약").value == StatusValue.CONFIRMED


def test_worst_같은_등급이면_앞_칸의_이유():
    first = Status(value="unverified", reason="body_missing")
    second = Status(value="unverified", reason="ambiguous")
    assert worst_status([C, first, second], "요약").reason == UnverifiedReason.BODY_MISSING


def test_worst_같은_등급이면_앞_칸의_범위():
    a = Status(value="not_found_in_scope", searched_scope="범위 A")
    b = Status(value="not_found_in_scope", searched_scope="범위 B")
    assert worst_status([a, b], "요약").searched_scope == "범위 A"


def test_worst_confirmed면_checked는_요약():
    s = worst_status([C, C], "모든 칸 원문 대조")
    assert s.checked == "모든 칸 원문 대조"


def test_worst_빈_목록은_unverified_not_extracted와_경고(caplog):
    with caplog.at_level(logging.WARNING):
        s = worst_status([], "요약")
    assert s.value == StatusValue.UNVERIFIED
    assert s.reason == UnverifiedReason.NOT_EXTRACTED
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ---------- 리뷰 반영: 빈 확인 내용·후보 타입·고정 ----------


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_checked와_범위가_비었거나_공백이면_거부(blank):
    with pytest.raises(ValidationError):
        Status(value="confirmed", checked=blank)
    with pytest.raises(ValidationError):
        Status(value="not_found_in_scope", searched_scope=blank)


def test_worst_confirmed에_빈_요약이면_거부():
    with pytest.raises(ValidationError):
        worst_status([C], "")


def test_후보_값도_T_타입_검사():
    with pytest.raises(ValidationError):
        ExtractedValue[list[int]](
            value=None,
            status=Status(value="conflict"),
            candidates=[
                {"value": "abc", "source": "rule"},
                {"value": [1, 2], "source": "model"},
            ],
        )


def test_만든_뒤_칸을_바꾸면_거부():
    s = Status(value="conflict")
    with pytest.raises(ValidationError):
        s.value = StatusValue.CONFIRMED
    base = ResultBase(status=s)
    with pytest.raises(ValidationError):
        base.needs_recheck = True
    # 새 값은 model_copy로 만든다
    assert base.model_copy(update={"needs_recheck": True}).needs_recheck is True
