"""read_oa 테스트: 지어낸 통지서 글자(fixture) + 가짜 전송층(사람이 쓴 답). 진짜 모델 호출 없음.

기대값은 docs/features/F1/design.md 9절 표에서 가져왔다.
"""

import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f1_oa_reader.read_oa import read_oa
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded, ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportError, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import NoticeKind

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f1"
STEP = "f1.read_oa"


def _pages(name: str) -> PageText:
    return PageText.model_validate_json((FIXTURES / f"{name}.pages.json").read_text("utf-8"))


def _pages_replaced(name: str, old: str, new: str) -> PageText:
    """fixture 글자 일부를 바꾼 쪽 글자 (다른 표기·다른 조문 시험용)."""
    data = json.loads((FIXTURES / f"{name}.pages.json").read_text("utf-8"))
    for page in data["pages"]:
        page["text"] = page["text"].replace(old, new)
    return PageText.model_validate(data)


def _answer(name: str):
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _run(pages_name: str, responses, *, budget: CallBudget | None = None):
    """read_oa를 가짜 전송층으로 돌린다. responses: 답 하나, 목록, 또는 예외."""
    transport = FakeTransport({STEP: responses} if responses is not None else {})
    ctx = RunContext(
        run_id="r_1", budget=budget or CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    result = read_oa(_pages(pages_name), "d_1", "oa_1", "r_1", ctx=ctx)
    return result, transport


def _ok(answer_name: str):
    return _text(_answer(answer_name))


def _all_confirmed(result) -> bool:
    values = [
        result.application_number,
        result.dispatch_number,
        result.notice_date,
        result.response_due,
        result.notice_kind,
        result.examiner_hints.allowable_claims,
        result.examiner_hints.amendment_note,
    ]
    for r in result.rejections:
        values += [r.article, r.claims, r.examiner_reasoning]
        for c in r.citations:
            values += [c.number, c.country, c.cited_paragraphs]
    return all(v.status.value == StatusValue.CONFIRMED for v in values)


# ---- notice_basic: 모든 필드 confirmed + 쪽, 청구항 1에 거절이유 둘 ----
def test_기본_통지서는_모든_필드가_확인됨이고_쪽이_붙는다():
    result, transport = _run("notice_basic", _ok("basic"))
    assert len(transport.calls) == 1 and transport.calls[0]["step"] == STEP
    assert _all_confirmed(result)
    assert result.status.value == StatusValue.CONFIRMED
    assert (result.application_number.value, result.application_number.page) == (
        "10-2099-0000001",
        1,
    )
    assert result.dispatch_number.value == "9-5-2099-000000001"
    # 날짜는 값 없이 원문 글자만
    assert (result.notice_date.value, result.notice_date.raw_text) == (None, "2099.01.26.")
    assert (result.response_due.value, result.response_due.raw_text) == (None, "2099.03.26.")
    assert result.notice_kind.value == NoticeKind.INITIAL
    assert result.examiner_hints.allowable_claims.value == [5, 7]
    assert result.examiner_hints.allowable_claims.page == 3
    assert result.examiner_hints.amendment_note.page == 3


def test_기본_통지서의_거절이유는_청구항_1이_둘에_들어간다():
    result, _ = _run("notice_basic", _ok("basic"))
    first, second = result.rejections
    assert (first.article.value, first.claims.value, first.claims.page) == ("29-2", [1, 2, 3, 4], 2)
    assert (second.article.value, second.claims.value, second.claims.page) == ("42-4-2", [1], 3)
    assert first.supported and second.supported
    assert 1 in first.claims.value and 1 in second.claims.value  # 합치지 않고 따로 둠
    numbers = [(c.number.value, c.country.value, c.cited_paragraphs.value) for c in first.citations]
    assert numbers == [
        ("KR10-0000001", "KR", ["0023", "0031"]),
        ("US 2099/0000001", "US", ["0045"]),
    ]
    assert all(c.country_supported for c in first.citations)
    # 요지는 모델 글, 원문 글자·쪽은 대조를 통과한 것
    assert first.examiner_reasoning.value.startswith("센서 구성")
    assert first.examiner_reasoning.page == 2


def test_모델은_통지서_글자를_담은_프롬프트로_한_번_부른다():
    _, transport = _run("notice_basic", _ok("basic"))
    assert "2099.03.26." in transport.calls[0]["prompt"]  # $pages 자리에 쪽 글자가 들어감


# ---- 통지 종류 ----
def test_최후거절이유통지는_final():
    result, _ = _run("notice_final", _ok("basic"))
    assert result.notice_kind.value == NoticeKind.FINAL
    assert (result.notice_kind.raw_text, result.notice_kind.page) == ("최후거절이유통지", 1)


def test_머리말은_있고_최후_표시가_없으면_initial_쪽_없음():
    result, _ = _run("notice_no_kind", _ok("basic"))
    kind = result.notice_kind
    assert kind.value == NoticeKind.INITIAL and kind.page is None
    assert kind.status.value == StatusValue.CONFIRMED and kind.status.checked


def test_머리말이_잘리면_통지_종류는_unknown_확인되지_않음():
    result, _ = _run("notice_header_cut", _ok("basic"))
    kind = result.notice_kind
    assert kind.value == NoticeKind.UNKNOWN
    assert kind.status.value == StatusValue.UNVERIFIED
    assert kind.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert result.status.value == StatusValue.UNVERIFIED  # 결과 전체도 나쁜 쪽으로


# ---- 힌트 칸 없음 ----
def test_심사관_힌트_칸이_없으면_없음이고_확인됨():
    result, _ = _run("notice_no_hints", _ok("no_hints"))
    claims, note = result.examiner_hints.allowable_claims, result.examiner_hints.amendment_note
    assert claims.value == [] and note.value is None
    for v in (claims, note):
        assert v.page is None and v.raw_text is None
        assert v.status.value == StatusValue.CONFIRMED
        assert v.status.checked == "원문에 칸 없음, 모든 쪽 글자를 봄"
    assert result.status.value == StatusValue.CONFIRMED


# ---- 못 뽑음 ----
def test_제출기일과_식별번호가_없으면_그_필드만_확인되지_않음():
    result, _ = _run("notice_missing_fields", _ok("missing_fields"))
    due = result.response_due
    assert (due.value, due.raw_text, due.page) == (None, None, None)
    assert due.status.value == StatusValue.UNVERIFIED
    assert due.status.reason == UnverifiedReason.NOT_EXTRACTED
    for c in result.rejections[0].citations:
        p = c.cited_paragraphs
        assert (p.value, p.raw_text, p.page) == (None, None, None)
        assert p.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert result.notice_date.status.value == StatusValue.CONFIRMED  # 다른 필드는 그대로
    assert result.status.value == StatusValue.UNVERIFIED


# ---- 지원 안 하는 조문·나라 ----
def test_지원_안_하는_조문과_나라는_직접_검토_필요_표시():
    result, _ = _run("notice_unsupported", _ok("unsupported"))
    first, second = result.rejections
    assert second.article.value == "42-3"
    assert not second.supported and Flag.NEEDS_HUMAN_REVIEW in second.flags
    assert first.supported and Flag.NEEDS_HUMAN_REVIEW not in first.flags
    kr, jp = first.citations
    assert kr.country_supported and not kr.flags
    assert jp.country.value == "JP" and not jp.country_supported
    assert Flag.NEEDS_HUMAN_REVIEW in jp.flags
    assert result.status.value == StatusValue.CONFIRMED  # flags로만 알리고 status는 안 바꿈


# ---- 글자 층 없음 ----
def test_글자_층이_없으면_모델을_안_부르고_필드_전부_input_unverified():
    result, transport = _run("notice_scanned", None)  # 답이 없는 전송층: 부르면 오류가 난다
    assert transport.calls == []
    fields = [
        result.application_number,
        result.dispatch_number,
        result.notice_date,
        result.response_due,
        result.notice_kind,
        result.examiner_hints.allowable_claims,
        result.examiner_hints.amendment_note,
    ]
    for v in fields:
        assert v.status.value == StatusValue.UNVERIFIED
        assert v.status.reason == UnverifiedReason.INPUT_UNVERIFIED
        assert v.raw_text is None and v.page is None
    assert result.status.value == StatusValue.UNVERIFIED  # failed로 끝내지 않고 결과를 돌려줌
    assert result.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert result.rejections == []


# ---- 모델 답 처리 ----
def test_원문에_없는_식별번호는_버리고_확인되지_않음():
    result, _ = _run("notice_basic", _ok("hallucinated"))
    p = result.rejections[0].citations[0].cited_paragraphs
    assert (p.value, p.raw_text, p.page) == (None, None, None)
    assert p.status.value == StatusValue.UNVERIFIED
    assert p.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert result.status.value == StatusValue.UNVERIFIED


def test_모델_출원번호가_규칙과_다르면_충돌로_둘_다_남긴다():
    result, _ = _run("notice_basic", _ok("conflict"))
    app = result.application_number
    assert app.status.value == StatusValue.CONFLICT and app.value is None
    assert {(c.source, c.value) for c in app.candidates} == {
        ("rule", "10-2099-0000001"),
        ("model", "10-2099-0000999"),
    }
    assert result.status.value == StatusValue.CONFLICT


def test_모델이_애매로_표시한_대상_청구항은_값_없이_확인되지_않음_애매():
    result, _ = _run("notice_basic", _ok("ambiguous"))
    claims = result.rejections[0].claims
    assert claims.value is None
    assert claims.status.value == StatusValue.UNVERIFIED
    assert claims.status.reason == UnverifiedReason.AMBIGUOUS
    assert (claims.raw_text, claims.page) == ("제1항 내지 제4항", 2)  # 대조 통과한 글자·쪽은 남음
    assert result.status.value == StatusValue.UNVERIFIED  # 결과 전체도 나쁜 쪽으로


def test_거절이유가_0개면_경고를_남기고_결과는_확인되지_않음(caplog):
    with caplog.at_level(logging.WARNING):
        result, _ = _run("notice_basic", _ok("no_rejections"))
    assert result.rejections == []
    assert result.status.value == StatusValue.UNVERIFIED
    assert result.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert any("거절이유 0개" in r.getMessage() for r in caplog.records)


# ---- 실패: 결과로 돌려주지 않고 예외를 그대로 던진다 ----
def test_모델_호출_오류는_ModelCallFailed로_던진다():
    with pytest.raises(ModelCallFailed):
        _run("notice_basic", TransportError("연결 안 됨", retryable=False))


def test_호출_상한을_넘으면_ModelCallLimitExceeded로_던진다():
    budget = CallBudget()
    budget.add("r_1", STEP, 0)
    budget.add("r_1", STEP, 0)  # config의 max_model_calls(2)를 이미 씀
    with pytest.raises(ModelCallLimitExceeded):
        _run("notice_basic", _ok("basic"), budget=budget)


def test_검사에_두_번_떨어지면_호출_2번_뒤_ModelOutputInvalid():
    bad = [_text(a) for a in _answer("invalid_twice")]
    transport = FakeTransport({STEP: bad})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelOutputInvalid):
        read_oa(_pages("notice_basic"), "d_1", "oa_1", "r_1", ctx=ctx)
    assert len(transport.calls) == 2


def test_첫_답이_검사에_떨어져도_두_번째가_맞으면_결과를_돌려준다():
    bad = _text(_answer("invalid_twice")[0])
    result, transport = _run("notice_basic", [bad, _ok("basic")])
    assert len(transport.calls) == 2
    assert result.status.value == StatusValue.CONFIRMED


# ---- 모으기: 칸 하나 conflict / 지원 안 하는 이유의 칸은 status를 안 바꿈 ----
def test_지원_안_하는_이유_안의_나쁜_칸은_결과_status를_안_바꾼다():
    answer = _answer("unsupported")
    answer["rejections"][1]["claims"]["ambiguous"] = True  # 42조 3항 이유의 청구항이 애매
    result, _ = _run("notice_unsupported", _text(answer))
    unsupported = result.rejections[1]
    assert unsupported.status.value == StatusValue.UNVERIFIED  # 그 이유 자체는 나쁨
    assert result.status.value == StatusValue.CONFIRMED  # 결과 전체는 그대로


def test_칸_하나가_충돌이면_결과_전체가_충돌():
    result, _ = _run("notice_basic", _ok("conflict"))
    assert result.status.value == StatusValue.CONFLICT


# ---- 리뷰 반영: 조문을 모르면 결과에 드러남, 힌트 칸이 있는데 모델이 null이면 확인되지 않음 ----
def test_조문을_모델이_못_뽑으면_그_거절이유는_직접_검토_필요이고_결과는_확인되지_않음():
    answer = _answer("basic")
    for r in answer["rejections"]:
        r["article"] = None
    result, _ = _run("notice_basic", _text(answer))
    for r in result.rejections:
        assert not r.supported and Flag.NEEDS_HUMAN_REVIEW in r.flags
        assert r.article.status.value == StatusValue.UNVERIFIED
    assert result.status.value == StatusValue.UNVERIFIED


def test_대조_통과한_지원_표_밖_조문은_결과_status를_안_바꾼다():
    pages = _pages_replaced("notice_unsupported", "제42조제3항", "제99조제9항")
    answer = json.loads(
        json.dumps(_answer("unsupported"), ensure_ascii=False).replace("제42조제3항", "제99조제9항")
    )
    transport = FakeTransport({STEP: _text(answer)})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    result = read_oa(pages, "d_1", "oa_1", "r_1", ctx=ctx)
    second = result.rejections[1]
    assert second.article.value == "99-9" and not second.supported
    assert Flag.NEEDS_HUMAN_REVIEW in second.flags
    assert result.status.value == StatusValue.CONFIRMED


def test_힌트_칸이_있는데_모델이_null이면_확인되지_않음():
    answer = _answer("basic")
    answer["allowable_claims"] = None
    answer["amendment_note"] = None
    result, _ = _run("notice_basic", _text(answer))
    for v in (result.examiner_hints.allowable_claims, result.examiner_hints.amendment_note):
        assert v.status.value == StatusValue.UNVERIFIED
        assert v.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert result.status.value == StatusValue.UNVERIFIED


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("「특허 가능한 청구항」", "특 허 가 능 한\n청 구 항"),  # 글자 사이 공백·줄바꿈
        ("【보정에 관한 참고사항】", "보정서 제출시 참고사항"),  # 다른 표기
    ],
)
def test_힌트_제목의_다른_표기도_찾아서_모델_null이면_확인되지_않음(old, new):
    pages = _pages_replaced("notice_basic", old, new)
    answer = _answer("basic")
    answer["allowable_claims"] = None
    answer["amendment_note"] = None
    transport = FakeTransport({STEP: _text(answer)})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    result = read_oa(pages, "d_1", "oa_1", "r_1", ctx=ctx)
    hints = result.examiner_hints
    target = hints.allowable_claims if "가능" in old else hints.amendment_note
    assert target.status.value == StatusValue.UNVERIFIED
