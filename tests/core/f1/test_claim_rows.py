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
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.propagation import collect_review_items

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
def test_평소_줄은_청구항_x_거절이유_하나씩이고_인용_없이_위치를_짚은_5_7항만_애매():
    result = _read()
    # 거절이유 2는 청구항 1~13 줄, 1은 청구항 1, 3은 청구항 6·7. 4번(지원 안 함)은 줄 없음
    keys = sorted((r.claim, r.rejection) for r in result.claim_rows)
    assert keys == sorted([(1, 1), *[(c, 2) for c in range(1, 14)], (6, 3), (7, 3)])
    # 3절 12: 3·9·10항은 같은 취지 대상 줄의 인용으로 정해져 확인됨.
    # 5-7항은 인용 언급 없이 위치([0069])를 짚었는데 거절이유 2 인용이 둘이라 어느 문헌인지 모름
    ambiguous = {(r.claim, r.rejection) for r in result.claim_rows if r.status.reason}
    assert ambiguous == {(c, 2) for c in (5, 6, 7)}
    assert all(
        r.status.value == StatusValue.CONFIRMED
        for r in result.claim_rows
        if (r.claim, r.rejection) not in ambiguous
    )
    assert result.status.value == StatusValue.UNVERIFIED


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


# ---- 원문 대조 실패: 그 줄만 unverified ----
def _assert_dropped(row, reason=UnverifiedReason.NOT_EXTRACTED):
    # 11/26 D3: 값을 버리지 않고 확인 안 된 모델 값으로 남긴다. 확인됨이 아니고, 값이 남았으면
    # 떨어진 검사(check_failed)가 꼭 적혀 있다 (사람이 "확인 필요"로 보게)
    assert row.status.value == StatusValue.UNVERIFIED and row.status.reason == reason
    kept = any((row.citations, row.locations, row.same_as, row.clarity_terms)) or row.raw_text
    assert not kept or (row.check_failed and row.check_failed.strip())
    assert row.clarity_reason is None


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


def test_청구항_번호를_못_읽으면_번호_없는_줄은_안_만들고_그_청구항은_빈_줄():
    answer = _with_row(
        0, claims={"value": None, "raw_text": "제A항", "page": 3, "ambiguous": False}
    )
    result = _read(answer)
    assert not [r for r in result.claim_rows if r.claim is None]
    _assert_dropped(_row(result, 1, 1))
    assert result.status.value == StatusValue.UNVERIFIED


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
    result = _read(answer)  # 거절이유 3의 대상은 제6·7항 (이 줄 판단 머리 번호도 1-1이라 어긋남)
    assert not [r for r in result.claim_rows if (r.claim, r.rejection) == (1, 3)]
    assert not [r for r in result.claim_rows if r.claim is None]  # 번호 없는 줄은 안 만듦
    _assert_dropped(_row(result, 1, 1))  # 원래 줄은 빈 줄로 채워짐
    assert result.status.value == StatusValue.UNVERIFIED


def test_같은_청구항_거절이유_줄이_겹치면_앞의_것만_남긴다():
    answer = _answer()
    answer["claim_rows"].append(copy.deepcopy(answer["claim_rows"][0]))
    assert len([r for r in _read(answer).claim_rows if (r.claim, r.rejection) == (1, 1)]) == 1


# ---- 줄이 없는 경우 ----
def test_모델이_줄을_안_주면_대상_청구항마다_빈_줄이고_결과가_확인되지_않음(caplog):
    answer = _answer()
    answer["claim_rows"] = []
    with caplog.at_level(logging.WARNING):
        result = _read(answer)
    assert "claim_rows" in caplog.text
    keys = sorted((r.claim, r.rejection) for r in result.claim_rows)
    assert keys == sorted([(1, 1), *[(c, 2) for c in range(1, 14)], (6, 3), (7, 3)])
    assert all(r.status.value == StatusValue.UNVERIFIED for r in result.claim_rows)
    assert result.status.value == StatusValue.UNVERIFIED
    items = collect_review_items([result], CaseMaterials(case_id="c_1"))
    targets = [i.target for i in items if "claim_rows" in i.target]
    assert len(targets) == 16 and "oa_result[oa_1].claim_rows[0]" in targets


def test_줄이_빠진_청구항은_그_줄만_빈_확인되지_않음_줄():
    answer = _answer()
    answer["claim_rows"] = [
        r for r in answer["claim_rows"] if not (r["claims"]["raw_text"] == "제2항")
    ]
    result = _read(answer)
    _assert_dropped(_row(result, 2, 2))
    assert _row(result, 4, 2).status.value == StatusValue.CONFIRMED  # 다른 줄은 그대로
    assert result.status.value == StatusValue.UNVERIFIED
    assert all(r.rejection != 4 for r in result.claim_rows)  # 지원 안 하는 이유는 채우지 않음


def test_대상_청구항을_모르는_거절이유는_빈_줄을_채우지_않는다():
    answer = _answer()
    answer["rejections"][1]["claims"]["raw_text"] = "제1항 내지 제A항"  # 청구항을 못 읽음
    answer["claim_rows"] = [r for r in answer["claim_rows"] if r["rejection"] != 2]
    result = _read(answer)
    assert all(r.rejection != 2 for r in result.claim_rows)
    assert result.status.value == StatusValue.UNVERIFIED  # 거절이유 status가 이미 확인되지 않음


# ---- 줄이 엇붙으면 확인되지 않음 (리뷰) ----
def test_거절이유에_없는_인용_라벨은_그_줄이_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][0]["citations"][0]["label"] = "D2"  # 거절이유 1의 인용은 D1뿐
    _assert_dropped(_row(_read(answer), 1, 1))


def test_인용_언급이_없는_줄의_인용은_모델_라벨이_아니라_규칙으로_정한다():
    answer = _answer()
    answer["claim_rows"][3]["citations"][0]["label"] = "D2"  # 3항 같은 취지 줄
    row = _row(_read(answer), 3, 2)
    # 3절 12: 모델이 D2라 해도 같은 취지 대상 (1, 2) 줄의 인용 D1
    assert row.citations == ["D1"] and row.same_as == ["claim:1"]
    assert row.status.value == StatusValue.CONFIRMED


def test_5_7항_줄은_인용은_규칙으로_정하고_위치는_어느_문헌인지_몰라_애매():
    result = _read()
    for claim in (5, 6, 7):  # 3절 10: "제5-7항 ... [0069]에 개시" (인용발명 언급 없음, 인용 둘)
        row = _row(result, claim, 2)
        # 3절 12 규칙 3: 인용은 거절이유 2 인용 전부. 위치는 모델 라벨 아래 그대로 남김
        assert row.citations == ["D1", "D2"] and row.locations == {"D1": ["[0069]"]}
        assert row.status.reason == UnverifiedReason.AMBIGUOUS  # ambiguous면 값·원문·쪽을 남김
        assert row.page == 4 and row.raw_text
    assert result.status.value == StatusValue.UNVERIFIED
    items = collect_review_items([result], CaseMaterials(case_id="c_1"))
    idx = result.claim_rows.index(_row(result, 5, 2))
    assert any(
        i.target == f"oa_result[oa_1].claim_rows[{idx}]" and i.reason == "ambiguous" for i in items
    )


def _single_citation_variant():
    """거절이유 1(인용 하나)의 판단에서 `인용발명 1의`를 뺀 통지서와 모델 답."""
    old, new = "인용발명 1의 [0014], [0056] 및 도 4b에 개시", "[0014], [0056] 및 도 4b에 개시"
    answer = _answer()
    j = answer["claim_rows"][0]["judgment"]
    j["raw_text"] = j["raw_text"].replace("인용발명 1의 ", "")
    return answer, _pages((old, new))


def test_판단_원문에_인용_언급이_없어도_거절이유_인용이_하나면_그_라벨():
    answer, pages = _single_citation_variant()
    answer["claim_rows"][0]["citations"][0]["label"] = None  # 라벨을 안 줘도 하나뿐이라 정해짐
    row = _row(_read(answer, pages), 1, 1)
    assert row.status.value == StatusValue.CONFIRMED and row.citations == ["D1"]
    assert row.locations == {"D1": ["[0014]", "[0056]", "도 4b"]}


def test_판단_원문이_거절이유_밖_인용을_언급하면_확인되지_않음():
    answer, pages = _single_citation_variant()
    j = answer["claim_rows"][0]["judgment"]
    j["raw_text"] = (
        "청구항 제1항은 인용발명 2의 [0014], [0056] 및 도 4b에 개시되어 있어 신규성이 없습니다."
    )
    pages = _pages(
        (
            "인용발명 1의 [0014], [0056] 및 도 4b에 개시",
            "인용발명 2의 [0014], [0056] 및 도 4b에 개시",
        )
    )
    _assert_dropped(_row(_read(answer, pages), 1, 1))  # 거절이유 1의 인용은 D1뿐


def test_판단_원문이_가리키는_인용과_모델_라벨이_다르면_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][1]["citations"][0]["label"] = "D2"  # 판단은 인용발명 1
    _assert_dropped(_row(_read(answer), 1, 2))


def test_라벨을_정할_수_없는데_위치가_있으면_ambiguous():
    answer = _answer()
    cit = answer["claim_rows"][5]["citations"][0]  # 5-7항 줄, 거절이유 2의 인용은 둘
    cit["label"] = None
    _assert_dropped(_row(_read(answer), 5, 2), UnverifiedReason.AMBIGUOUS)


def test_청구항_번호_원문이_판단_원문_안에_없으면_번호_없는_줄은_안_만들고_경고(caplog):
    answer = _answer()
    answer["claim_rows"][2]["claims"]["raw_text"] = "제3항"  # 판단은 제2항 이야기
    with caplog.at_level(logging.WARNING):
        result = _read(answer)
    assert _row(result, 3, 2).same_as == ["claim:1"]  # 3항 줄은 그대로 (덮어쓰지 않음)
    _assert_dropped(_row(result, 2, 2))  # 2항은 번호 있는 빈 줄로 채워짐
    assert not [r for r in result.claim_rows if r.claim is None]
    assert "번호" in caplog.text


def test_판단_원문_머리_번호와_거절이유_순번이_다르면_확인되지_않음():
    answer = _with_row(12, rejection=2)  # 7항 명확성 줄(3-2.)을 거절이유 2로 붙임
    result = _read(answer)
    _assert_dropped(_row(result, 7, 3))  # 빈 줄로 채워짐
    assert _row(result, 7, 2).locations == {"D1": ["[0069]"]}  # 5-7항 줄 값 그대로
    assert result.status.value == StatusValue.UNVERIFIED


def test_명확성_이유는_AI가_쓴_글로_구분한다():
    result = _read()
    quoted = _row(result, 6, 3)
    assert quoted.clarity_reason == "앞에 정의 없음"
    assert quoted.clarity_reason_origin == "ai_generated"
    assert _row(result, 7, 3).clarity_reason_origin is None
    assert _row(result, 1, 1).clarity_reason_origin is None


def test_claim_rows_칸이_없는_모델_답도_받지만_줄이_빠진_것으로_본다():
    answer = _answer()
    del answer["claim_rows"]
    result = _read(answer)
    assert len(result.claim_rows) == 16
    assert all(r.status.value == StatusValue.UNVERIFIED for r in result.claim_rows)


# ---- task-7: 인용이 하나도 없는 줄의 `위치 없음 (<OA 표현>)` ----
def _no_citation_variant(expression: str = "설계 사항"):
    """8항 줄을 `단순 부가` 대신 `설계 사항`만 적고 인용은 안 짚은 줄로 바꾼 통지서와 답."""
    answer = _answer()
    row = answer["claim_rows"][6]
    row["citations"] = []
    row["judgment"]["raw_text"] = row["judgment"]["raw_text"].replace("인용발명 1에 비추어 ", "")
    row["judgment"]["raw_text"] = row["judgment"]["raw_text"].replace("단순 부가", "설계 사항")
    row["no_location"] = {"value": None, "raw_text": expression, "page": 4, "ambiguous": False}
    pages = _pages(("인용발명 1에 비추어 단순 부가에 해당", "설계 사항에 해당"))
    return answer, pages


def test_인용_언급_없는_줄의_위치_없음은_거절이유_인용이_여럿이면_애매():
    answer, pages = _no_citation_variant()
    # 3절 12 규칙 3으로 인용이 D1·D2가 되고, 3절 4: 위치 없음이 어느 인용 것인지 원문에 없음
    _assert_dropped(_row(_read(answer, pages), 8, 2), UnverifiedReason.AMBIGUOUS)


def test_인용이_없는_거절이유의_줄은_위치_없음_표현을_no_location에_담는다():
    answer, pages = _no_citation_variant()
    answer["rejections"][1]["citations"] = []  # 거절이유 2에 인용문헌이 없다고 본 답
    row = _row(_read(answer, pages), 8, 2)
    assert row.status.value == StatusValue.CONFIRMED
    assert row.no_location == "위치 없음 (설계 사항)"
    assert row.citations == [] and row.locations == {}


def test_위치_없음_표현이_판단_원문_안에_없으면_그_줄은_확인되지_않음():
    answer, pages = _no_citation_variant("불명확")  # 4쪽 어딘가엔 있지만 이 줄 판단 문장엔 없음
    _assert_dropped(_row(_read(answer, pages), 8, 2))


def test_위치_없음_표현이_원문_어디에도_없으면_그_줄은_확인되지_않음():
    answer, pages = _no_citation_variant("지어낸 표현")
    _assert_dropped(_row(_read(answer, pages), 8, 2))


def test_인용_있는_줄의_위치_없음은_그대로_locations_라벨_아래():
    row = _row(_read(), 8, 2)
    assert row.locations == {"D1": ["위치 없음 (단순 부가)"]} and row.no_location is None


def test_평소_줄은_no_location이_비어_있다():
    assert all(r.no_location is None for r in _read().claim_rows)


# ---- 인용 있는 줄의 줄 단위 no_location (리뷰) ----
def _row_level(index: int, expression: str, *, ambiguous: bool = False) -> dict:
    answer = _answer()
    answer["claim_rows"][index]["no_location"] = {
        "value": None,
        "raw_text": expression,
        "page": answer["claim_rows"][index]["judgment"]["page"],
        "ambiguous": ambiguous,
    }
    return answer


def test_인용이_하나이고_위치가_없으면_줄_단위_위치_없음을_그_인용_위치로_옮긴다():
    answer = _row_level(6, "단순 부가")  # 8항 줄
    answer["claim_rows"][6]["citations"][0]["no_location"] = None  # 인용 안에는 안 줄 때
    row = _row(_read(answer), 8, 2)
    assert row.status.value == StatusValue.CONFIRMED
    assert row.locations == {"D1": ["위치 없음 (단순 부가)"]} and row.no_location is None


def test_인용이_여럿이면_줄_단위_위치_없음은_어느_인용인지_몰라_애매():
    answer = _row_level(2, "결합")  # 2항 줄: 인용 D1·D2
    _assert_dropped(_row(_read(answer), 2, 2), UnverifiedReason.AMBIGUOUS)


def test_인용이_하나여도_이미_위치가_있으면_줄_단위_위치_없음은_애매():
    answer = _row_level(0, "신규성이 없습니다")  # 1항 줄: D1에 위치가 있음
    _assert_dropped(_row(_read(answer), 1, 1), UnverifiedReason.AMBIGUOUS)


def test_줄_단위_위치_없음에_애매_표시가_있으면_그_줄은_ambiguous():
    answer = _row_level(6, "단순 부가", ambiguous=True)
    _assert_dropped(_row(_read(answer), 8, 2), UnverifiedReason.AMBIGUOUS)


def test_명확성_줄에_줄_단위_위치_없음이_오면_버리고_경고(caplog):
    answer = _row_level(11, "불명확")  # 6항 명확성 줄
    with caplog.at_level(logging.WARNING):
        row = _row(_read(answer), 6, 3)
    assert row.status.value == StatusValue.CONFIRMED and row.no_location is None
    assert "위치 없음" in caplog.text


# ---- 목록 칸(clarity_terms·same_as)에 문자열이 온 답 (11/19 tune 5건 실패 원인) ----
def _read_twice(first: dict, second: dict):
    """첫 답·두 번째 답을 차례로 주는 가짜 전송층으로 read_oa를 돌린다."""
    texts = [TransportResponse(json.dumps(a, ensure_ascii=False), 100, 50) for a in (first, second)]
    transport = FakeTransport({STEP: texts})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return read_oa(_pages(), "d_1", "oa_1", "r_1", ctx=ctx), transport


def _string_terms() -> dict:
    """6항 명확성 줄의 clarity_terms를 {raw_text, page} 객체 대신 문자열로 준 답."""
    answer = _answer()
    answer["claim_rows"][11]["clarity_terms"] = ["상기 프리뷰 이미지"]
    return answer


def _string_same_as() -> dict:
    """3항 줄의 same_as를 객체 대신 문자열로 준 답."""
    answer = _answer()
    answer["claim_rows"][3]["same_as"] = ["제1항과 동일한 취지"]
    return answer


def test_첫_답의_목록_칸이_문자열이면_재시도_프롬프트에_검사_오류가_들어간다():
    result, transport = _read_twice(_string_terms(), _answer())
    assert len(transport.calls) == 2
    first, second = transport.calls[0]["prompt"], transport.calls[1]["prompt"]
    assert "출력 형식 검사" not in first  # 첫 호출에는 재시도 안내가 없다
    assert "출력 형식 검사" in second and "clarity_terms" in second  # 검사 오류 문구
    # 두 번째 답이 맞으면 그 줄은 평소대로 확인됨
    assert _row(result, 6, 3).status.value == StatusValue.CONFIRMED


def test_두_번째도_clarity_terms가_문자열이면_실행은_돌고_그_줄만_확인되지_않음():
    result, transport = _read_twice(_string_terms(), _string_terms())
    assert len(transport.calls) == 2
    row = _row(result, 6, 3)
    _assert_dropped(row)  # 문자열(원문·쪽 없음)은 확인됨으로 새지 않는다
    assert row.clarity_terms == []
    assert _row(result, 1, 1).status.value == StatusValue.CONFIRMED  # 다른 줄은 그대로
    assert result.status.value == StatusValue.UNVERIFIED


def test_두_번째도_same_as가_문자열이면_실행은_돌고_그_줄만_확인되지_않음():
    result, _ = _read_twice(_string_same_as(), _string_same_as())
    row = _row(result, 3, 2)
    _assert_dropped(row)
    assert row.same_as == []
    assert _row(result, 4, 2).same_as == ["rejection:1"]  # 다른 줄의 같은 취지는 그대로


def test_목록_칸_말고_다른_곳의_문자열은_두_번째에도_검사에_떨어진다():
    answer = _answer()
    answer["claim_rows"][0]["judgment"] = "판단 문장"  # Item 칸에 문자열
    try:
        _read_twice(answer, answer)
    except ModelOutputInvalid:
        return
    raise AssertionError("ModelOutputInvalid가 나야 함")


# ---- 청구항 번호 원문이 애매한 줄 (11/19 tune: "청구항 제9항(제6항 인용)") ----
_CITED = ("청구항 제8항은", "청구항 제8항(제1항 인용)은")  # 8항 판단 원문에 인용항 괄호를 넣음


def _cited_answer() -> dict:
    answer = copy.deepcopy(_answer())
    row = answer["claim_rows"][6]
    row["claims"]["raw_text"] = "제8항(제1항 인용)"
    row["judgment"]["raw_text"] = (
        "청구항 제8항(제1항 인용)은 인용발명 1에 비추어 단순 부가에 해당합니다."
    )
    return answer


def test_인용항_괄호가_붙은_번호는_괄호_밖_번호의_줄로_남기되_애매이고_확인됨이_아니다():
    result = _read(_cited_answer(), _pages(_CITED))
    row = _row(result, 8, 2)
    _assert_dropped(row, UnverifiedReason.AMBIGUOUS)  # 값·원문·쪽 없음, 확인됨 금지
    assert not [r for r in result.claim_rows if r.claim is None]  # 번호 없는 줄은 여전히 안 만듦


def test_인용항_괄호_줄보다_같은_청구항의_확인된_줄이_있으면_그_줄이_남는다():
    answer = _cited_answer()
    good = copy.deepcopy(_answer()["claim_rows"][6])  # 평소 8항 줄 (원문 그대로)
    answer["claim_rows"].append(good)
    pages = _pages(_CITED)
    # 평소 8항 줄의 판단 원문도 쪽에 있도록 원문 줄을 하나 더 둔다
    data = json.loads(pages.model_dump_json())
    data["pages"][3]["text"] += "\n2-7. 청구항 제8항은 인용발명 1에 비추어 단순 부가에 해당합니다."
    result = _read(answer, PageText.model_validate(data))
    assert _row(result, 8, 2).status.value == StatusValue.CONFIRMED


def test_괄호_밖도_못_읽으면_번호_없는_줄은_만들지_않는다():
    answer = _cited_answer()
    answer["claim_rows"][6]["claims"]["raw_text"] = "제A항(제1항 인용)"
    pages = _pages(("청구항 제8항은", "청구항 제A항(제1항 인용)은"))
    answer["claim_rows"][6]["judgment"]["raw_text"] = (
        "청구항 제A항(제1항 인용)은 인용발명 1에 비추어 단순 부가에 해당합니다."
    )
    result = _read(answer, pages)
    assert not [r for r in result.claim_rows if r.claim is None]
    _assert_dropped(_row(result, 8, 2))  # 대상 청구항 빈 줄로 채워짐 (not_extracted)


def test_인용항_괄호_줄이라도_거절이유_대상_밖_청구항이면_줄을_만들지_않는다():
    answer = _cited_answer()
    answer["claim_rows"][6]["rejection"] = 3  # 거절이유 3의 대상은 제6·7항
    result = _read(answer, _pages(_CITED))
    assert not [r for r in result.claim_rows if (r.claim, r.rejection) == (8, 3)]


# ---- 정답 3절 12: 판단 문장에 인용발명이 없는 줄의 인용 (모델이 고르지 않음) ----
def _variant(*pairs: tuple[str, str]):
    """통지서 글자와 모델 답 글자에서 old를 new로 바꾼 것 (pairs 순서대로)."""
    text = json.dumps(_answer(), ensure_ascii=False)
    data = json.loads((FIXTURES / "notice_claim_rows.pages.json").read_text("utf-8"))
    for old, new in pairs:
        text = text.replace(old, new)
        for page in data["pages"]:
            page["text"] = page["text"].replace(old, new)
    return json.loads(text), PageText.model_validate(data)


_RULE_ALL = "문장에 인용 표기 없음, 거절이유 인용 전부로 봄"


def test_3절_12_문장에_인용이_있으면_그_문헌만():
    result = _read()
    assert _row(result, 13, 2).citations == ["D2"]  # 거절이유 2 인용은 둘이지만 문장엔 인용발명 2
    row = _row(result, 1, 2)  # 같은 취지(rejection:1)도 있지만 문장에 인용발명 1이 먼저
    assert row.citations == ["D1"] and row.status.value == StatusValue.CONFIRMED
    assert _RULE_ALL not in (row.status.checked or "")


def test_3절_12_문장에_적힌_인용은_모델이_빠뜨려도_넣는다():
    answer = _answer()
    answer["claim_rows"][2]["citations"] = answer["claim_rows"][2]["citations"][:1]  # D1만 줌
    row = _row(_read(answer), 2, 2)  # "인용발명 1 내지 2의 결합"
    assert row.citations == ["D1", "D2"] and row.locations == {"D1": ["[0020]"]}
    assert row.status.value == StatusValue.CONFIRMED


def test_3절_12_같은_취지_claim은_같은_거절이유_청구항_줄의_인용():
    row = _row(_read(), 3, 2)  # 제1항과 동일한 취지 -> (1, 2) 줄의 인용 D1 (D1·D2 전부가 아님)
    assert row.citations == ["D1"] and row.same_as == ["claim:1"]
    assert row.locations == {}  # 3절 1: 대상 줄의 위치는 복사하지 않음
    assert row.status.value == StatusValue.CONFIRMED and "같은 취지" in row.status.checked


def test_3절_12_같은_취지_rejection은_같은_청구항_거절이유_줄의_인용():
    answer, pages = _variant(
        ("1-1에서 본 바와 같이 인용발명 1에 의해 쉽게", "1-1에서 본 바와 같이 쉽게")
    )
    result = _read(answer, pages)
    row = _row(result, 1, 2)  # 2-1에 인용발명 언급이 없어짐 -> (1, 1) 줄의 인용 D1
    assert row.citations == ["D1"] and row.same_as == ["rejection:1"]
    assert row.status.value == StatusValue.CONFIRMED
    assert _row(result, 3, 2).citations == ["D1"]  # 대상의 대상까지 따라간다


def test_3절_12_같은_취지_대상이_여럿이면_인용을_합친다():
    result = _read()
    for claim in (9, 10):  # 청구항 제1항(D1) 내지 제2항(D1+D2)과 같음
        row = _row(result, claim, 2)
        assert row.citations == ["D1", "D2"] and row.locations == {}
        assert row.status.value == StatusValue.CONFIRMED
        assert "같은 취지" in row.status.checked and _RULE_ALL not in row.status.checked


def test_3절_12_같은_취지_대상이_여럿이면_중복_빼고_합친다():
    answer, pages = _variant(("청구항 제1항 내지 제2항과 같", "청구항 제1항 및 제3항과 같"))
    row = _row(_read(answer, pages), 9, 2)  # (1, 2)=D1, (3, 2)=D1 -> D1 하나
    assert row.same_as == ["claim:1", "claim:3"] and row.citations == ["D1"]
    assert row.status.value == StatusValue.CONFIRMED


def test_3절_12_인용_언급도_같은_취지도_없으면_거절이유_인용_전부이고_확인됨():
    answer = _answer()
    answer["claim_rows"][5]["citations"][0]["location"] = None  # 5-7항 줄이 위치를 안 짚게
    result = _read(answer)
    for claim in (5, 6, 7):
        row = _row(result, claim, 2)
        assert row.citations == ["D1", "D2"] and row.locations == {}
        assert row.status.value == StatusValue.CONFIRMED and _RULE_ALL in row.status.checked


def test_3절_12_언급_없는_줄도_거절이유_밖_라벨이면_확인되지_않음():
    answer = _answer()
    answer["claim_rows"][5]["citations"][0]["label"] = "D9"
    _assert_dropped(_row(_read(answer), 5, 2))


def test_3절_12_같은_취지_대상_줄이_확인되지_않음이면_이_줄도(caplog):
    answer = _with_row(
        1, judgment={"value": None, "raw_text": "지어낸 문장", "page": 3, "ambiguous": False}
    )
    with caplog.at_level(logging.WARNING):
        result = _read(answer)
    _assert_dropped(_row(result, 1, 2))
    for claim in (3, 9, 10):  # (1, 2) 줄을 가리키는 같은 취지 줄
        _assert_dropped(_row(result, claim, 2))
    assert "같은 취지" in caplog.text


def test_3절_12_같은_취지_대상_청구항_줄이_없으면_확인되지_않음(caplog):
    answer, pages = _variant(("제1항과 동일한 취지", "제20항과 동일한 취지"))  # 대상 밖 청구항
    with caplog.at_level(logging.WARNING):
        result = _read(answer, pages)
    _assert_dropped(_row(result, 3, 2))
    assert "같은 취지" in caplog.text


def test_3절_12_같은_취지_대상이_지원_안_하는_거절이유면_확인되지_않음():
    answer, pages = _variant(
        ("1-1에서 본 바와 같이 인용발명 1에 의해 쉽게", "4-1에서 본 바와 같이 쉽게"),
        ('"1-1에서 본 바와 같이"', '"4-1에서 본 바와 같이"'),
    )
    result = _read(answer, pages)
    row = _row(result, 1, 2)  # (1, 4) 줄은 만들지 않음 (3절 9)
    _assert_dropped(row)


def test_3절_12_같은_취지가_돌아서_제자리로_오면_확인되지_않음(caplog):
    answer, pages = _variant(
        ("제1항과 동일한 취지", "제9항과 동일한 취지"),
        ("청구항 제1항 내지 제2항과 같", "청구항 제3항과 같"),
    )
    with caplog.at_level(logging.WARNING):
        result = _read(answer, pages)
    for claim in (3, 9, 10):  # 3 -> 9 -> 3, 10 -> 3 -> 9 -> 3
        _assert_dropped(_row(result, claim, 2))
    assert "순환" in caplog.text
    assert _row(result, 2, 2).status.value == StatusValue.CONFIRMED  # 다른 줄은 그대로


def test_3절_12_같은_취지_줄의_줄_단위_위치_없음은_어느_인용인지_몰라_애매():
    answer = _row_level(3, "동일한 취지")  # 3항 줄: 인용은 대상 줄에서 정해짐
    _assert_dropped(_row(_read(answer), 3, 2), UnverifiedReason.AMBIGUOUS)


# ---- 같은 취지 줄이 위치를 짚은 경우 (PR #125 리뷰 고칠 것 1번) ----
# 같은 취지 줄의 인용은 대상 줄에서 채우므로, 위치는 인용을 채운 뒤 붙여야 한다
_NO_MENTION_4 = ("한편 인용발명 2의 [0043]에도", "한편 [0043]에도")  # 4항 줄에서 인용 언급을 뺌
_SAME_AS_1 = ("거절이유 1과 같고", "청구항 제1항과 같고")  # 4항 줄의 대상을 (1, 2) 줄(인용 D1)로


def test_같은_취지_줄이_위치를_짚어도_멈추지_않는다():
    answer, pages = _variant(_NO_MENTION_4)  # 리뷰 재현 그대로
    result = _read(answer, pages)  # 예외 없이 끝나야 함
    # 대상 rejection:1 -> (4, 1) 줄은 없음 (거절이유 1의 대상은 제1항뿐)
    # 3절 12 규칙대로 확인되지 않음
    _assert_dropped(_row(result, 4, 2))
    assert _row(result, 3, 2).status.value == StatusValue.CONFIRMED  # 다른 같은 취지 줄은 그대로


def test_같은_취지_줄이_채운_인용_밖_라벨에_위치를_짚으면_애매():
    answer, pages = _variant(_NO_MENTION_4, _SAME_AS_1)
    row = _row(_read(answer, pages), 4, 2)
    # 모델은 [0043]을 D2 아래 짚었는데 채운 인용은 D1뿐: 어느 인용의 위치인지 원문으로 못 정함
    _assert_dropped(row, UnverifiedReason.AMBIGUOUS)


def test_같은_취지_줄이_채운_인용_안_라벨에_위치를_짚으면_위치를_붙이고_확인됨():
    # (1, 1): 거절이유 1(인용 D1 하나)의 판단에서 인용 언급을 빼고 2-1과 같은 취지로 바꿈
    answer, pages = _variant(
        ("청구항 제1항은 인용발명 1의 [0014]", "청구항 제1항은 2-1에서 본 바와 같이 [0014]")
    )
    answer["claim_rows"][0]["same_as"] = [
        {"value": None, "raw_text": "2-1에서 본 바와 같이", "page": 3, "ambiguous": False}
    ]
    row = _row(_read(answer, pages), 1, 1)  # 대상 (1, 2) 줄의 인용 D1
    assert row.same_as == ["rejection:2"] and row.citations == ["D1"]
    assert row.locations == {"D1": ["[0014]", "[0056]", "도 4b"]}
    assert row.status.value == StatusValue.CONFIRMED and "같은 취지" in row.status.checked


def test_같은_취지_줄의_위치가_이미_애매여도_멈추지_않고_위치를_남긴_애매():
    answer, pages = _variant(_NO_MENTION_4, _SAME_AS_1)
    answer["claim_rows"][4]["citations"][0]["label"] = "D1"  # 채운 인용(D1) 안 라벨
    row = _row(_read(answer, pages), 4, 2)
    # 거절이유 2 인용이 둘이고 언급이 없어 location_ambiguous: 값은 남기되 애매 (원래 판정 그대로)
    assert row.status.value == StatusValue.UNVERIFIED
    assert row.status.reason == UnverifiedReason.AMBIGUOUS
    assert row.citations == ["D1"] and row.locations == {"D1": ["[0043]"]}
    assert row.same_as == ["claim:1"] and row.page == 3 and row.raw_text


# ---- 위치 원문은 그 줄 판단 원문 안에 있어야 확인됨 (이슈 #161) ----
# 이슈 #161 정한 것: 위치 원문이 그 줄 판단 원문 밖이면 그 줄은 unverified(ambiguous),
# 값·원문·쪽은 남긴다. 지어낸 모양: 11·12항을 한 줄로 묶고, 판단 원문은 두 항을 묶은 결론 문장,
# 위치 글자는 같은 쪽 11항 문단.
_CONCLUSION = (
    "따라서 청구항 제11항 및 제12항 발명은 인용발명 1 및 2의 결합에 의하여 쉽게 발명할 수 있습니다."
)


def _bundled(judgment: str, extra_line: str | None = None):
    """11·12항(답의 8·9번째 줄)을 한 줄로 묶은 모델 답과, 필요하면 4쪽 끝에 한 줄 더한 통지서."""
    answer = _answer()
    bundle = copy.deepcopy(answer["claim_rows"][8])  # 11항 줄: D1 [16, 38, 78]
    bundle["claims"]["raw_text"] = "제11항 및 제12항"
    bundle["judgment"]["raw_text"] = judgment
    answer["claim_rows"][8:10] = [bundle]
    pages = _pages()
    if extra_line:
        data = pages.model_dump()
        page = next(p for p in data["pages"] if p["page"] == 4)
        page["text"] = page["text"].replace("\n3-1.", f"\n{extra_line}\n3-1.")
        pages = PageText.model_validate(data)
    return answer, pages


def test_묶은_결론_문장_밖의_위치면_묶인_줄_모두_애매이고_확인된_위치는_없다():
    answer, pages = _bundled(_CONCLUSION, extra_line=_CONCLUSION)
    result = _read(answer, pages)
    for claim in (11, 12):
        row = _row(result, claim, 2)
        assert row.status.value == StatusValue.UNVERIFIED
        assert row.status.reason == UnverifiedReason.AMBIGUOUS
        # 값·원문·쪽은 남긴다 (사람이 보고 고를 수 있게)
        assert row.locations == {"D1": ["[0016]", "[0038]", "[0078]"]}
        assert row.citations == ["D1", "D2"]
        assert row.raw_text == _CONCLUSION and row.page == 4
    confirmed_locations = [
        loc
        for r in result.claim_rows
        if r.claim in (11, 12) and r.status.value == StatusValue.CONFIRMED
        for loc in r.locations.values()
    ]
    assert confirmed_locations == []
    assert _row(result, 13, 2).status.value == StatusValue.CONFIRMED  # 다른 줄은 그대로


def test_묶은_줄이라도_위치가_판단_원문_안이면_줄마다_같은_위치로_확인됨():
    # 3절 10번: 묶어 짚은 청구항은 줄마다 같은 위치 (위치 글자가 판단 원문 안)
    judgment = "청구항 제11항 및 제12항은 인용발명 1의 [16, 38, 78]에 개시되어 있습니다."
    answer, pages = _bundled(judgment, extra_line=judgment)
    result = _read(answer, pages)
    for claim in (11, 12):
        row = _row(result, claim, 2)
        assert row.status.value == StatusValue.CONFIRMED
        assert row.locations == {"D1": ["[0016]", "[0038]", "[0078]"]}


def test_위치_원문이_판단_원문_밖이면_묶지_않은_줄도_애매():
    # 13항 줄 판단 원문을 2-10 문단 앞부분만으로 줄임: 위치 [0050]은 판단 원문 밖, 같은 쪽 안
    answer = _answer()
    answer["claim_rows"][10]["judgment"]["raw_text"] = "청구항 제13항은 인용발명 2의"
    row = _row(_read(answer), 13, 2)
    assert row.status.value == StatusValue.UNVERIFIED
    assert row.status.reason == UnverifiedReason.AMBIGUOUS
    assert row.locations == {"D2": ["[0050]"]} and row.page == 4


# ---- 11/26 P4 원인 표: 지나치게 엄한 검사 ----
def test_쪽_머리_출원번호_숫자가_머리_번호에_붙어도_줄을_버리지_않는다():
    # 쪽 첫 줄 출원번호 뒤 줄바꿈 없이 이어 읽히면 '…12342-3.'이 되어 머리 번호를 큰 수로 읽었다
    pages = _pages(replace=("2-3. 청구항 제3항", "10-2099-0001234\n2-3. 청구항 제3항"))
    row = _row(_read(pages=pages), 3, 2)
    assert row.status.value == StatusValue.CONFIRMED


def test_모델이_청구항_글자를_바꿔_써도_판단_원문의_번호와_같으면_줄을_만든다():
    # 판단 원문은 '청구항 제2항은…', 모델은 청구항 글자를 '청구항 2'로 줌 (쪽에 그 글자 없음)
    claims = {"value": None, "raw_text": "청구항 2", "page": 3, "ambiguous": False}
    row = _row(_read(_with_row(2, claims=claims)), 2, 2)
    assert row.status.value == StatusValue.CONFIRMED and row.citations


def test_판단_원문에_없는_번호를_청구항_글자로_주면_여전히_줄을_만들지_않는다():
    # 2항 판단 원문에 '9항'이 없으니 그 줄로 9항 줄을 만들지 않고, 2항은 모델이 안 준 빈 줄
    claims = {"value": None, "raw_text": "청구항 9", "page": 3, "ambiguous": False}
    result = _read(_with_row(2, claims=claims))
    assert (_row(result, 9, 2).raw_text or "").startswith("청구항 제9항")
    assert _row(result, 2, 2).status.value == StatusValue.UNVERIFIED


def test_위치_글자가_판단_원문_안이면_그_칸_쪽_번호가_달라도_통과():
    answer = copy.deepcopy(_answer())
    answer["claim_rows"][0]["citations"][0]["location"]["page"] = 4  # 판단은 3쪽
    row = _row(_read(answer), 1, 1)
    assert row.status.value == StatusValue.CONFIRMED
    assert row.locations == {"D1": ["[0014]", "[0056]", "도 4b"]}


def test_두_곳_위치를_쌍반점으로_이어_줘도_조각마다_대조한다():
    answer = copy.deepcopy(_answer())
    answer["claim_rows"][0]["citations"][0]["location"]["raw_text"] = "[0014], [0056]; 도 4b"
    row = _row(_read(answer), 1, 1)
    assert row.status.value == StatusValue.CONFIRMED
    assert row.locations == {"D1": ["[0014]", "[0056]", "도 4b"]}


def test_쌍반점으로_이은_조각_하나가_원문에_없으면_여전히_확인되지_않음():
    answer = copy.deepcopy(_answer())
    answer["claim_rows"][0]["citations"][0]["location"]["raw_text"] = "[0014]; [0099]"
    row = _row(_read(answer), 1, 1)
    assert row.status.value == StatusValue.UNVERIFIED


# ---- 11/26 D3: 원문 대조에 떨어진 줄도 모델 값을 남긴다 (status는 unverified + 떨어진 검사) ----
def test_대조에_떨어진_줄도_모델_값을_남기고_떨어진_검사를_적는다():
    answer = copy.deepcopy(_answer())
    answer["claim_rows"][0]["citations"][0]["location"]["raw_text"] = (
        "[0014]; [0099]"  # [0099]는 원문에 없음
    )
    row = _row(_read(answer), 1, 1)
    assert row.status.value == StatusValue.UNVERIFIED
    assert row.raw_text.startswith("청구항 제1항은 인용발명 1의") and row.page == 3
    assert row.citations == ["D1"]
    assert row.locations == {"D1": ["[0014]", "[0099]"]}  # 모델이 준 위치 (확인 안 됨)
    assert row.check_failed  # 어느 검사에서 떨어졌나 (사람이 볼 글)


def test_확인된_줄에는_떨어진_검사_칸이_없다():
    row = _row(_read(), 1, 1)
    assert row.status.value == StatusValue.CONFIRMED and row.check_failed is None


def test_모델이_줄을_주지_않은_빈_줄은_값이_없다():
    answer = copy.deepcopy(_answer())
    del answer["claim_rows"][6]  # 8항 줄
    row = _row(_read(answer), 8, 2)
    assert row.status.value == StatusValue.UNVERIFIED
    assert row.raw_text is None and row.citations == [] and row.check_failed is None


def test_같은_취지_대상_줄이_위치만_애매하면_인용은_물려받아_확인된다():
    # 5-7항 줄은 인용 언급 없이 위치만 짚어 애매(위치만). 그 줄의 인용은 원문 규칙으로 정해져 있다
    answer = copy.deepcopy(_answer())
    answer["claim_rows"][6]["same_as"] = [
        {"value": None, "raw_text": "제5-7항", "page": 4, "ambiguous": False}
    ]
    answer["claim_rows"][6]["judgment"]["raw_text"] = "2-6. 청구항 제8항은 인용발명 1에 비추어"
    pages = _pages(
        replace=(
            "청구항 제8항은 인용발명 1에 비추어",
            "청구항 제8항은 제5-7항과 같고 인용발명 1에 비추어",
        )
    )
    answer["claim_rows"][6]["judgment"]["raw_text"] = "청구항 제8항은 제5-7항과 같고"
    answer["claim_rows"][6]["citations"] = []
    target = _row(_read(answer, pages), 5, 2)
    row = _row(_read(answer, pages), 8, 2)
    assert target.status.reason == UnverifiedReason.AMBIGUOUS
    assert row.status.value == StatusValue.CONFIRMED
    assert row.citations == target.citations


# ---- 11/26 골 모드 뒤 case08 원인 (work/opinion-goal-1126/FOLLOWUP_1126.md) ----
def test_청구항_번호가_판단_원문_바로_앞_문장에_있으면_줄을_만든다():
    # 모델이 판단 원문을 "청구항 제7항에는 …" 다음 문장부터 줬다
    # → 번호가 바로 앞 문장에 있으면 맞는 줄
    pages = _pages(
        (
            "3-2. 청구항 제7항의 모듈들은 장치 구성을 특정할 수 없다.",
            "3-2. 청구항 제7항에는 모듈이 기재되어 있습니다. "
            "상기 모듈들은 장치 구성을 특정할 수 없다.",
        )
    )
    judgment = {"value": None, "raw_text": "상기 모듈들은 장치 구성을 특정할 수 없다.", "page": 4,
                "ambiguous": False}  # fmt: skip
    row = _row(_read(_with_row(12, judgment=judgment), pages), 7, 3)
    assert row.raw_text == "상기 모듈들은 장치 구성을 특정할 수 없다."
    # 번호가 판단 원문 밖이라 그 항의 줄인지 원문으로 확실히 정하지 못함: 확인됨으로 올리지 않고
    # 값은 남긴다 (의견서는 '확인 필요'로 받음)
    assert row.status.value == StatusValue.UNVERIFIED
    assert row.status.reason == UnverifiedReason.AMBIGUOUS
    assert row.check_failed and "앞 문장" in row.check_failed


def test_번호가_두_문장_넘어_앞에_있으면_맞는_줄이_아니다():
    pages = _pages(
        (
            "3-2. 청구항 제7항의 모듈들은 장치 구성을 특정할 수 없다.",
            "3-2. 청구항 제7항에는 모듈이 있습니다. 다른 말입니다. "
            "상기 모듈들은 장치 구성을 특정할 수 없다.",
        )
    )
    judgment = {"value": None, "raw_text": "상기 모듈들은 장치 구성을 특정할 수 없다.", "page": 4,
                "ambiguous": False}  # fmt: skip
    _assert_dropped(_row(_read(_with_row(12, judgment=judgment), pages), 7, 3))


def test_겹친_줄은_앞이_확인되지_않음이고_뒤가_확인됨이면_뒤를_남긴다():
    # case08: '청구항 2 내지 7'(같은 취지 애매) 줄이 앞, '제7 및 14항'(문제 표현 있음) 줄이 뒤
    answer = _answer()
    first = copy.deepcopy(answer["claim_rows"][12])
    first["judgment"] = {**first["judgment"], "ambiguous": True}
    answer["claim_rows"].insert(0, first)
    row = _row(_read(answer), 7, 3)
    assert row.status.value == StatusValue.CONFIRMED
