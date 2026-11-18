"""청구항 줄(claim_rows)과 명확성 표현 테스트.

기대값은 정답 형식(docs/evaluation/f1-oa-gold.md 2.4·3절·4절)과 tasks.md m1-i2-18 task-6에서
가져왔다. 통지서 글자(notice_claim_rows)와 모델 답(llm/claim_rows.json)은 지어낸 값이고, 모델 답은
사람이 직접 쓴 FakeTransport 답이다. 진짜 모델 호출 없음.
"""

import copy
import json
import logging
from pathlib import Path

from patent_ai.core.f1_oa_reader.read_oa import read_oa
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f1"
STEP = "f1.read_oa"


def _pages(replace: tuple[str, str] | None = None) -> PageText:
    data = json.loads((FIXTURES / "notice_claim_rows.pages.json").read_text("utf-8"))
    if replace:
        for page in data["pages"]:
            page["text"] = page["text"].replace(*replace)
    return PageText.model_validate(data)


def _answer() -> dict:
    return json.loads((FIXTURES / "llm" / "claim_rows.json").read_text("utf-8"))


def _read(answer: dict | None = None, pages: PageText | None = None):
    answer = answer if answer is not None else _answer()
    text = TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)
    ctx = RunContext(
        run_id="r_1",
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=FakeTransport({STEP: text}),
    )
    return read_oa(pages or _pages(), "d_1", "oa_1", "r_1", ctx=ctx)


def _row(result, claim: int, rejection: int):
    rows = [r for r in result.claim_rows if (r.claim, r.rejection) == (claim, rejection)]
    assert len(rows) == 1, f"청구항 {claim} 거절이유 {rejection} 줄이 {len(rows)}개"
    return rows[0]


def _with_row(index: int, **change) -> dict:
    """모델 답의 index번째 줄을 바꾼 답 (바꾼 칸만 다름)."""
    answer = copy.deepcopy(_answer())
    answer["claim_rows"][index].update(change)
    return answer


# ---- 평소 ----
def test_평소_줄은_청구항_x_거절이유_하나씩이고_모두_확인됨():
    result = _read()
    assert result.status.value == StatusValue.CONFIRMED
    assert all(r.status.value == StatusValue.CONFIRMED for r in result.claim_rows)
    # 거절이유 2는 청구항 1~13 줄, 1은 청구항 1, 3은 청구항 6·7. 4번(지원 안 함)은 줄 없음
    keys = sorted((r.claim, r.rejection) for r in result.claim_rows)
    assert keys == sorted([(1, 1), *[(c, 2) for c in range(1, 14)], (6, 3), (7, 3)])


def test_청구항_하나에_거절이유가_여럿이면_줄도_여럿():
    result = _read()
    first = _row(result, 1, 1)
    second = _row(result, 1, 2)
    assert first.citations == ["D1"]
    assert first.locations == {"D1": ["[0014]", "[0056]", "도 4b"]}
    assert first.same_as == [] and first.page == 3
    assert first.raw_text.startswith("청구항 제1항은 인용발명 1의")
    assert second.rejection == 2
    assert (_row(result, 6, 2).rejection, _row(result, 6, 3).rejection) == (2, 3)


def test_줄은_결과_evidence에_들어간다():
    result = _read()
    raws = [e.raw_text for e in result.evidence]
    assert any("신규성이 없습니다" in (raw or "") for raw in raws)


# ---- 정답 3절 1~11 ----
def test_3절_1_같은_취지는_위치를_비우고_같은_취지만():  # 1
    row = _row(_read(), 3, 2)
    assert row.locations == {} and row.same_as == ["claim:1"]


def test_3절_2_짝_없는_같은_취지는_펼친_목록():  # 2
    result = _read()
    for claim in (9, 10):
        assert _row(result, claim, 2).same_as == ["claim:1", "claim:2"]
        assert _row(result, claim, 2).locations == {}


def test_3절_3_자기_위치와_같은_취지_둘_다():  # 3
    row = _row(_read(), 4, 2)
    assert row.same_as == ["rejection:1"]
    assert row.locations == {"D2": ["[0043]"]} and row.citations == ["D2"]


def test_3절_4_위치_없음은_표현을_그대로_적는다():  # 4
    row = _row(_read(), 8, 2)
    assert row.locations == {"D1": ["위치 없음 (단순 부가)"]}


def test_3절_5_도면_부호만_짚으면_부호_그대로():  # 5
    assert _row(_read(), 12, 2).locations == {"D2": ["폐곡선(310, 320)"]}


def test_3절_6_문단_번호는_4자리로_맞춘다():  # 6
    assert _row(_read(), 11, 2).locations == {"D1": ["[0016]", "[0038]", "[0078]"]}


def test_3절_7_결합_진보성은_인용_둘_위치는_짚은_것만():  # 7
    row = _row(_read(), 2, 2)
    assert row.citations == ["D1", "D2"]
    assert row.locations == {"D1": ["[0020]"]}


def test_3절_8_앞에서_본_바와_같이는_거절이유를_가리킨다():  # 8
    row = _row(_read(), 1, 2)
    assert row.same_as == ["rejection:1"] and row.locations == {}


def test_3절_9_지원_안_하는_이유는_표에만_두고_줄은_만들지_않는다():  # 9
    result = _read()
    unsupported = result.rejections[3]
    assert unsupported.article.value == "42-3" and not unsupported.supported
    assert all(r.rejection != 4 for r in result.claim_rows)
    assert _row(result, 13, 2).locations == {"D2": ["[0050]"]}  # 다른 지원 이유 줄은 그대로


def test_3절_10_묶어서_짚은_청구항은_줄마다_같은_위치():  # 10
    result = _read()
    for claim in (5, 6, 7):
        row = _row(result, claim, 2)
        assert row.locations == {"D1": ["[0069]"]} and row.page == 4


def test_3절_11_따옴표_없는_명확성은_표현이_빈_목록():  # 11
    result = _read()
    quoted = _row(result, 6, 3)
    assert quoted.clarity_terms == ["상기 프리뷰 이미지"]
    assert quoted.clarity_reason == "앞에 정의 없음"
    assert quoted.citations == [] and quoted.locations == {}
    plain = _row(result, 7, 3)
    assert plain.clarity_terms == [] and plain.status.value == StatusValue.CONFIRMED


def test_거절이유_종류가_결과에_붙는다():
    kinds = [r.kind for r in _read().rejections]
    assert kinds == ["novelty", "inventive_step", "clarity", "other"]


# ---- 원문 대조 실패: 그 줄만 unverified, 값은 버림 ----
def _assert_dropped(row, reason=UnverifiedReason.NOT_EXTRACTED):
    assert row.status.value == StatusValue.UNVERIFIED and row.status.reason == reason
    assert (row.citations, row.locations, row.same_as, row.clarity_terms) == ([], {}, [], [])
    assert row.raw_text is None and row.page is None and row.clarity_reason is None


def test_판단_원문이_그_쪽에_없으면_그_줄만_확인되지_않음():
    answer = _with_row(
        0, judgment={"value": None, "raw_text": "지어낸 문장", "page": 3, "ambiguous": False}
    )
    result = _read(answer)
    _assert_dropped(_row(result, 1, 1))
    assert _row(result, 1, 2).status.value == StatusValue.CONFIRMED  # 다른 줄은 그대로
    assert result.status.value == StatusValue.UNVERIFIED


def test_판단_원문이_다른_쪽_글자면_확인되지_않음():
    answer = _with_row(
        0,
        judgment={
            "value": None,
            "raw_text": _answer()["claim_rows"][0]["judgment"]["raw_text"],
            "page": 4,
            "ambiguous": False,
        },
    )
    _assert_dropped(_row(_read(answer), 1, 1))


def test_위치는_모델_value가_아니라_원문_글자에서_다시_뽑는다():
    answer = _answer()
    answer["claim_rows"][0]["citations"][0]["location"]["value"] = ["[9999]"]
    assert _row(_read(answer), 1, 1).locations == {"D1": ["[0014]", "[0056]", "도 4b"]}


def test_위치_글자가_원문에_없으면_그_줄이_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][0]["citations"][0]["location"]["raw_text"] = "[0099]"
    _assert_dropped(_row(_read(answer), 1, 1))


def test_위치_글자를_못_읽으면_그_줄이_확인되지_않음():
    answer = _answer()
    # 원문에는 있지만 위치 꼴이 아닌 조각이 섞인 글자
    answer["claim_rows"][0]["citations"][0]["location"]["raw_text"] = "[0056] 및 도 4b에 개시"
    _assert_dropped(_row(_read(answer), 1, 1))


def test_청구항_번호를_못_읽으면_번호_없는_확인되지_않음_줄_하나():
    answer = _with_row(
        0, claims={"value": None, "raw_text": "제A항", "page": 3, "ambiguous": False}
    )
    result = _read(answer)
    bad = [r for r in result.claim_rows if r.claim is None]
    assert len(bad) == 1
    _assert_dropped(bad[0])


def test_없는_거절이유_순번이면_확인되지_않음():
    result = _read(_with_row(0, rejection=9))
    bad = [r for r in result.claim_rows if r.rejection is None]
    assert len(bad) == 1 and bad[0].claim == 1
    _assert_dropped(bad[0])


def test_인용_라벨을_모르면_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][0]["citations"][0]["label"] = "D9"
    _assert_dropped(_row(_read(answer), 1, 1))


def test_인용_원문으로도_라벨을_찾는다():
    answer = _answer()
    cit = answer["claim_rows"][0]["citations"][0]
    cit["label"] = None
    cit["number"] = {"value": None, "raw_text": "인용발명 1", "page": 3, "ambiguous": False}
    row = _row(_read(answer), 1, 1)
    assert row.citations == ["D1"] and row.status.value == StatusValue.CONFIRMED


def test_같은_취지_글자가_원문에_없으면_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][3]["same_as"][0]["raw_text"] = "제2항과 동일한 취지"
    _assert_dropped(_row(_read(answer), 3, 2))


def test_따옴표_밖_글자를_명확성_표현으로_주면_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][11]["clarity_terms"][0]["raw_text"] = "앞에 정의가 없어"
    _assert_dropped(_row(_read(answer), 6, 3))


def test_따옴표_없는_줄에_명확성_표현을_주면_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][12]["clarity_terms"] = [
        {"value": None, "raw_text": "모듈들", "page": 4, "ambiguous": False}
    ]
    _assert_dropped(_row(_read(answer), 7, 3))


def test_애매_표시가_붙은_값이_있으면_그_줄은_ambiguous():
    answer = _answer()
    answer["claim_rows"][0]["citations"][0]["location"]["ambiguous"] = True
    _assert_dropped(_row(_read(answer), 1, 1), UnverifiedReason.AMBIGUOUS)


def test_거절이유_대상_밖_청구항이면_그_줄은_확인되지_않음():
    answer = _with_row(
        0, claims={"value": None, "raw_text": "제1항", "page": 3, "ambiguous": False}, rejection=3
    )
    result = _read(answer)  # 거절이유 3의 대상은 제6·7항
    _assert_dropped(_row(result, 1, 3))


def test_같은_청구항_거절이유_줄이_겹치면_앞의_것만_남긴다():
    answer = _answer()
    answer["claim_rows"].append(copy.deepcopy(answer["claim_rows"][0]))
    assert len([r for r in _read(answer).claim_rows if (r.claim, r.rejection) == (1, 1)]) == 1


# ---- 줄이 없는 경우 ----
def test_모델이_줄을_안_주면_빈_목록이고_경고(caplog):
    answer = _answer()
    answer["claim_rows"] = []
    with caplog.at_level(logging.WARNING):
        result = _read(answer)
    assert result.claim_rows == []
    assert "claim_rows" in caplog.text


def test_claim_rows_칸이_없는_모델_답도_받는다():
    answer = _answer()
    del answer["claim_rows"]
    assert _read(answer).claim_rows == []
