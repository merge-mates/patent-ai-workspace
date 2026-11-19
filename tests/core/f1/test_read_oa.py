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
        result.examined_claims,
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
        "1020990000001",
        1,
    )
    assert result.application_number.raw_text == "10-2099-0000001"  # 원문 그대로
    assert result.dispatch_number.value == "952099000000001"
    assert result.dispatch_number.raw_text == "9-5-2099-000000001"
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
    assert (first.kind, second.kind) == ("inventive_step", "clarity")  # 조문에서 규칙으로 정함
    assert 1 in first.claims.value and 1 in second.claims.value  # 합치지 않고 따로 둠
    numbers = [(c.number.value, c.country.value, c.cited_paragraphs.value) for c in first.citations]
    assert numbers == [
        ("KR20990000001A", "KR", ["[0023]", "[0031]"]),
        ("US20990000001A1", "US", ["[0045]"]),
    ]
    # 번호 글자는 원문 표기 그대로
    assert [c.number.raw_text for c in first.citations] == [
        "공개특허공보 제10-2099-0000001호",
        "US 2099/0000001 A1",
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
    assert (first.kind, second.kind) == ("inventive_step", "other")
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
        result.examined_claims,
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
        ("rule", "1020990000001"),
        ("model", "1020990000999"),
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


# ---- #18: 값 모양을 정답 형식(f1-oa-gold.md)에 맞춘다 ----
def _run_with(pages: PageText, answer):
    transport = FakeTransport({STEP: _text(answer)})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return read_oa(pages, "d_1", "oa_1", "r_1", ctx=ctx)


def _swap(name: str, answer_name: str, old: str, new: str):
    """쪽 글자와 모델 답 양쪽의 같은 글자를 바꾼다 (원문 대조를 통과하도록)."""
    pages = _pages_replaced(name, old, new)
    answer = json.loads(json.dumps(_answer(answer_name), ensure_ascii=False).replace(old, new))
    return pages, answer


def test_심사_대상_청구항은_펼친_번호로_원문과_쪽이_붙는다():
    result, _ = _run("notice_basic", _ok("basic"))
    ec = result.examined_claims
    assert ec.value == [1, 2, 3, 4, 5, 6, 7]
    assert (ec.raw_text, ec.page) == ("제1항 내지 제7항", 1)
    assert ec.status.value == StatusValue.CONFIRMED


def test_심사_대상_청구항을_못_뽑으면_확인되지_않음이고_결과도_나쁜_쪽():
    answer = _answer("basic")
    answer["examined_claims"] = None
    result = _run_with(_pages("notice_basic"), answer)
    assert result.examined_claims.value is None
    assert result.examined_claims.status.value == StatusValue.UNVERIFIED
    assert result.status.value == StatusValue.UNVERIFIED


def test_청구항_전항은_심사_대상_청구항_전부로_펼친다():
    pages, answer = _swap("notice_basic", "basic", "제1항 내지 제4항", "청구항 전항")
    answer["examined_claims"]["raw_text"] = "제1항 내지 제7항"
    result = _run_with(pages, answer)
    first = result.rejections[0]
    assert first.claims.value == [1, 2, 3, 4, 5, 6, 7]
    assert first.claims.raw_text == "청구항 전항"
    assert first.claims.status.value == StatusValue.CONFIRMED


def test_청구항_전항인데_심사_대상을_모르면_펼치지_못해_확인되지_않음():
    pages, answer = _swap("notice_basic", "basic", "제1항 내지 제4항", "청구항 전항")
    answer["examined_claims"] = None
    result = _run_with(pages, answer)
    claims = result.rejections[0].claims
    assert claims.value is None and claims.status.value == StatusValue.UNVERIFIED


def test_거절이유는_순번_인용문헌은_나온_순서로_라벨이_붙고_같은_문헌은_같은_라벨():
    pages = _pages_replaced(
        "notice_basic", "[첨 부]", "인용발명 1: 공개특허공보 제10-2099-0000001호 (도 4c)\n[첨 부]"
    )
    answer = _answer("basic")
    answer["rejections"][1]["citations"] = [
        {
            "number": {"raw_text": "공개특허공보 제10-2099-0000001호", "page": 3},
            "cited_paragraphs": {"raw_text": "도 4c", "page": 3},
        }
    ]
    result = _run_with(pages, answer)
    assert [r.no for r in result.rejections] == [1, 2]
    first, second = result.rejections
    assert [c.label for c in first.citations] == ["D1", "D2"]
    assert [c.label for c in second.citations] == ["D1"]  # 같은 문헌
    assert second.citations[0].cited_paragraphs.value == ["도 4c"]


def test_논문은_번호_값_없이_확인되지_않음_애매이고_직접_검토_필요():
    old = "US 2099/0000001 A1"
    new = "Kim, Fake Sensors, 2099 학회 논문"
    pages, answer = _swap("notice_basic", "basic", old, new)
    result = _run_with(pages, answer)
    npl = result.rejections[0].citations[1]
    assert npl.number.value is None
    assert npl.number.status.value == StatusValue.UNVERIFIED
    assert npl.number.status.reason == UnverifiedReason.AMBIGUOUS
    assert npl.number.raw_text == new  # 원문 표기는 남긴다
    assert not npl.country_supported and Flag.NEEDS_HUMAN_REVIEW in npl.flags


def test_못_읽는_식별번호_조각이_있으면_그_칸만_확인되지_않음_애매():
    old, new = "(식별번호 [0045])", "(식별번호 [0045], 어딘가)"
    pages, answer = _swap("notice_basic", "basic", old, new)
    answer["rejections"][0]["citations"][1]["cited_paragraphs"]["raw_text"] = (
        "식별번호 [0045], 어딘가"
    )
    result = _run_with(pages, answer)
    first, second = result.rejections[0].citations
    assert first.cited_paragraphs.value == ["[0023]", "[0031]"]
    p = second.cited_paragraphs
    assert p.value is None
    assert p.status.value == StatusValue.UNVERIFIED
    assert p.status.reason == UnverifiedReason.AMBIGUOUS
    assert p.raw_text == "식별번호 [0045], 어딘가"


def test_호가_여럿인_조문은_세로줄로_이어_모두_지원이면_지원():
    pages, answer = _swap(
        "notice_basic", "basic", "특허법 제29조제2항", "특허법 제29조제1항제1호 및 제2호"
    )
    result = _run_with(pages, answer)
    first = result.rejections[0]
    assert first.article.value == "29-1-1|29-1-2"
    assert first.supported and Flag.NEEDS_HUMAN_REVIEW not in first.flags


# ---- task-8: 쪽을 넘어간 거절이유 표 칸 ----
_HEAD = ["순번", "거절이유가 있는 부분", "관련 법조항"]


def _pages_with_split_table() -> PageText:
    """notice_basic 1쪽 끝에 거절이유 표를 두고, 1번 줄 대상 청구항 칸이 2쪽 맨 위로 넘어간 모양.

    2쪽 첫 표: 순번이 빈 이어지는 줄 + 2번 줄 (tune OA에서 본 모양, 이슈 #18 댓글).
    """
    data = json.loads((FIXTURES / "notice_basic.pages.json").read_text("utf-8"))
    data["pages"][0]["text"] += (
        "\n순번 거절이유가 있는 부분 관련 법조항\n1 청구항 제1항 내지 특허법 제29조제2항\n1/3"
    )
    data["pages"][0]["tables"] = [[_HEAD, ["1", "청구항 제1항 내지", "특허법 제29조제2항"]]]
    # 2쪽 본문 속 "제1항 내지 제4항"은 지워, 쪽 글자만으로는 대상 청구항을 대조할 수 없게 한다
    body = data["pages"][1]["text"].replace("청구항 제1항 내지 제4항은", "청구항은")
    data["pages"][1]["text"] = (
        "10-2099-0000001\n제4항\n2 청구항 제1항 특허법 제42조제4항제2호\n" + body
    )
    data["pages"][1]["tables"] = [
        [["", "제4항", ""], ["2", "청구항 제1항", "특허법 제42조제4항제2호"]]
    ]
    return PageText.model_validate(data)


def _run_pages(pages: PageText, answer):
    transport = FakeTransport({STEP: _text(answer)})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return read_oa(pages, "d_1", "oa_1", "r_1", ctx=ctx)


def test_쪽을_넘어간_대상_청구항_칸은_이어_붙여_확인됨이고_시작_쪽이다():
    answer = _answer("basic")
    # 모델은 표 칸을 이어 읽어 1쪽 글자로 줬다 (쪽 글자만으로는 두 쪽에 걸쳐 대조가 안 됨)
    answer["rejections"][0]["claims"] = {
        "value": None,
        "raw_text": "청구항 제1항 내지 제4항",
        "page": 1,
        "ambiguous": False,
    }
    result = _run_pages(_pages_with_split_table(), answer)
    claims = result.rejections[0].claims
    assert claims.status.value == StatusValue.CONFIRMED
    assert claims.value == [1, 2, 3, 4]
    assert claims.page == 1
    assert result.rejections[0].article.value == "29-2"


def test_모델이_대상_청구항을_못_줘도_표_줄에서_확인됨():
    answer = _answer("basic")
    answer["rejections"][0]["claims"] = None
    result = _run_pages(_pages_with_split_table(), answer)
    claims = result.rejections[0].claims
    assert claims.value == [1, 2, 3, 4]
    assert claims.status.value == StatusValue.CONFIRMED
    assert claims.page == 1  # 줄이 시작한 쪽
    assert claims.raw_text == "청구항 제1항 내지 제4항"  # 이어 붙인 칸 글자


def test_다음_쪽_조각을_못_찾은_쪽_끝_줄은_규칙_값을_안_써서_잘린_값이_확인됨이_되지_않는다():
    data = json.loads(_pages_with_split_table().model_dump_json())
    # 칸이 "…제3항" | ", 제4항"처럼 잘려 1쪽 칸 끝에 이음말이 없는 모양
    data["pages"][0]["tables"] = [[_HEAD, ["1", "청구항 제1항 내지 제3항", "특허법 제29조제2항"]]]
    data["pages"][1]["tables"] = []  # 2쪽 조각이 표로 안 잡힘
    answer = _answer("basic")
    answer["rejections"][0]["claims"] = None
    result = _run_pages(PageText.model_validate(data), answer)
    claims = result.rejections[0].claims
    assert claims.status.value == StatusValue.UNVERIFIED  # [1,2,3]으로 확인됨이 되지 않음
    assert claims.value is None


def test_표_줄과_모델의_대상_청구항이_다르면_conflict():
    answer = _answer("basic")
    answer["rejections"][0]["claims"] = {
        "value": None,
        "raw_text": "제1항",
        "page": 3,
        "ambiguous": False,
    }
    result = _run_pages(_pages_with_split_table(), answer)
    claims = result.rejections[0].claims
    assert claims.status.value == StatusValue.CONFLICT
    assert sorted(tuple(c.value) for c in claims.candidates) == [(1,), (1, 2, 3, 4)]


# ---- 모델 입력 모양 (이슈 #122 task-b): config read_oa.model_input ----
def _with_model_input(monkeypatch, value):
    """read_oa가 읽는 단계 설정의 model_input만 바꾼다 (나머지는 config/f1.yaml 그대로)."""
    import dataclasses

    from patent_ai.core.f1_oa_reader import read_oa as module
    from patent_ai.core.llm.config import load_step_config

    real = load_step_config(STEP)
    monkeypatch.setattr(
        module, "load_step_config", lambda step: dataclasses.replace(real, model_input=value)
    )


def _pages_with_table() -> PageText:
    pages = _pages("notice_basic")
    first = pages.pages[0].model_copy(
        update={
            "tables": [
                [
                    ["순번", "거절이유가 있는 부분", "관련 법조항"],
                    ["1", "청구항 제1항", "특허법 제29조제2항"],
                ]
            ]
        }
    )
    return pages.model_copy(update={"pages": [first, *pages.pages[1:]]})


def _prompt_for(pages: PageText) -> str:
    transport = FakeTransport({STEP: _ok("basic")})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    read_oa(pages, "d_1", "oa_1", "r_1", ctx=ctx)
    return transport.calls[0]["prompt"]


def test_config의_model_input은_정한_값_중_하나다():
    from patent_ai.core.f1_oa_reader.model_input import MODES
    from patent_ai.core.llm.config import load_step_config

    assert load_step_config(STEP).model_input in MODES


def test_tables_md면_표가_마크다운으로_모델_입력에_들어간다(monkeypatch):
    _with_model_input(monkeypatch, "tables_md")
    prompt = _prompt_for(_pages_with_table())
    assert "[쪽 1 표]\n| 순번 | 거절이유가 있는 부분 | 관련 법조항 |" in prompt


def test_raw면_표를_덧붙이지_않는다(monkeypatch):
    _with_model_input(monkeypatch, "raw")
    assert "[쪽 1 표]" not in _prompt_for(_pages_with_table())


@pytest.mark.parametrize("value", [None, "markdown"])
def test_model_input이_없거나_모르는_값이면_모델을_부르지_않고_멈춘다(monkeypatch, value):
    from patent_ai.core.llm.errors import ModelConfigError

    _with_model_input(monkeypatch, value)
    transport = FakeTransport({STEP: _ok("basic")})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelConfigError, match="model_input"):
        read_oa(_pages("notice_basic"), "d_1", "oa_1", "r_1", ctx=ctx)
    assert transport.calls == []
