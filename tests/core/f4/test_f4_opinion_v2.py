"""의견서만 (11/26 골 모드 P5): 보정안 단계를 끄고 바깥 보정 결과로 의견서를 쓴다.

기대값은 11/26 지시문 P5 task 1·2·4와 D2-1에서 가져왔다:
- `amendment_enabled: false`면 보정안 단계(f4.amendment)를 부르지 않는다
- 의견서는 묶음마다 반박(f4.opinion_unit)만,
  사건 전체 한 번(f4.opinion_case)으로 요약·보정 설명·결론
- 보정 설명 칸 유무는 방향 후보가 아니라 바깥 보정 결과로 정한다. 어긋나면 표시를 남긴다
- 항별 심사관 근거에 원문 대조에 떨어진 줄도 "확인 필요"로 싣는다 (값이 남은 줄만)
- 스위치 켬(기본)이면 지금 동작 그대로
"""

import dataclasses
import json
from pathlib import Path

from patent_ai.core.f4_response_draft.config import load_f4_options
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.drafts import OpinionKey
from patent_ai.core.schemas.oa_result import ClaimRow, OAResult, summarize_status

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
OK = {"value": "confirmed", "checked": "원문 대조"}
UNV = {"value": "unverified", "reason": "not_extracted"}

AMENDED_1 = (
    "기판 위에 놓인 센서와, 상기 센서를 덮는 투명 덮개를 포함하고 "
    "김 서림 방지 막을 둔 가상의 센서 장치."
)
ORACLE = {
    "source": "보정서 접수번호 1",
    "claims": [
        {"claim": 1, "change": "amended", "before": None, "after": AMENDED_1},
        {"claim": 3, "change": "deleted", "before": None, "after": None},
    ],
}


def _case(amendment=ORACLE) -> dict:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    data["oa"]["claim_rows"] = [
        {
            "claim": 2,
            "rejection": 1,
            "citations": ["D1"],
            "locations": {"D1": ["[0021]"]},
            "raw_text": "제2항의 김 서림 방지 막은 인용발명 1의 식별번호 [0021]에 개시",
            "page": 2,
            "status": OK,
        },
        {
            # 원문 대조에 떨어졌지만 모델 값이 남은 줄 (D3)
            "claim": 1,
            "rejection": 1,
            "citations": ["D1"],
            "locations": {"D1": ["[0033]"]},
            "raw_text": "제1항은 인용발명 1의 [0033]과 같다",
            "page": 2,
            "status": UNV,
            "check_failed": "위치 글자를 원문 쪽에서 못 찾음",
        },
        {"claim": 3, "rejection": 1, "status": UNV},  # 모델이 준 값 없음: 싣지 않음
    ]
    # 떨어진 줄이 있으니 결과 전체 status를 칸에서 다시 모은다 (OAResult 검사)
    oa = data["oa"]
    rows = [ClaimRow.model_validate(r) for r in oa["claim_rows"]]
    probe = OAResult.model_validate({**oa, "claim_rows": []})
    fields = {k: getattr(probe, k) for k in (
        "oa_id", "application_number", "dispatch_number", "notice_date", "response_due",
        "notice_kind", "examined_claims", "examiner_hints", "rejections", "examined_claim_version",
    )}  # fmt: skip
    oa["status"] = summarize_status(**fields, claim_rows=rows).model_dump(mode="json")
    if amendment is not None:
        data["external_amendment"] = amendment
    return data


def _resp(obj) -> TransportResponse:
    return TransportResponse(json.dumps(obj, ensure_ascii=False), 100, 50)


def _answer(name: str) -> TransportResponse:
    return TransportResponse((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"), 100, 50)


UNIT_OUT = {"response": "보정한 청구항 1의 김 서림 방지 막은 인용발명 1에 없다고 주장합니다."}
CASE_WITH = {
    "points": "심사관은 진보성과 명확성을 지적했습니다.",
    "amendment": "청구항 1을 한정하고 청구항 3을 삭제했습니다.",
    "closing": "검토를 부탁드립니다.",
}
CASE_WITHOUT = {**CASE_WITH, "amendment": None}


def _run(amendment=ORACLE, case_out=CASE_WITH, enabled=False):
    transport = FakeTransport(
        {
            "f4.direction": [_answer("direction_inventive"), _answer("direction_clarity")],
            "f4.opinion_unit": [_resp(UNIT_OUT), _resp(UNIT_OUT)],
            "f4.opinion_case": [_resp(case_out)],
            "f4.opinion": [_answer("opinion_inventive"), _answer("opinion_clarity")],
            "f4.amendment": [_answer("amendment_inventive"), _answer("amendment_clarity")],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    options = dataclasses.replace(load_f4_options(), amendment_enabled=enabled)
    out = run_f4(F4Input.model_validate(_case(amendment)), ctx=ctx, options=options)
    return out, transport


def test_기본값은_보정안_단계_켬():
    assert load_f4_options().amendment_enabled is True


def test_끄면_보정안_단계를_부르지_않고_묶음마다_반박_사건마다_한_번():
    _, t = _run()
    steps = [c["step"] for c in t.calls]
    assert "f4.amendment" not in steps and "f4.opinion" not in steps
    assert steps.count("f4.opinion_unit") == 2 and steps.count("f4.opinion_case") == 1


def test_바깥_보정_결과가_반박_프롬프트에_들어간다():
    _, t = _run()
    unit = [c for c in t.calls if c["step"] == "f4.opinion_unit"][0]["prompt"]
    assert "김 서림 방지 막을 둔 가상의 센서 장치" in unit  # 보정 뒤 글자
    assert "삭제" in unit


def test_묶음_반박은_system_칸을_쓴다():
    _, t = _run()
    unit = [c for c in t.calls if c["step"] == "f4.opinion_unit"][0]
    assert unit.get("system")


def test_보정_설명_칸은_바깥_보정_결과가_있으면_있고_코드_표가_붙는다():
    out, _ = _run()
    sections = {s.key: s.ai_text for s in out.drafts.opinion}
    assert OpinionKey.AMENDMENT in sections
    assert "제1항" in sections[OpinionKey.AMENDMENT] and "제3항" in sections[OpinionKey.AMENDMENT]
    assert [s.key for s in out.drafts.opinion][0] == OpinionKey.CASE_INFO


def test_바깥_보정_결과가_없으면_보정_설명_칸이_없다_방향이_보정이어도():
    # 방향 후보 1순위는 보정+반박인데 바깥 보정 결과가 없다: 출력 검사 실패가 아니라 칸 없음
    out, t = _run(amendment=None, case_out=CASE_WITHOUT)
    assert OpinionKey.AMENDMENT not in {s.key for s in out.drafts.opinion}
    unit = [c for c in t.calls if c["step"] == "f4.opinion_unit"][0]["prompt"]
    assert "보정 결과 없음" in unit
    assert out.direction_amendment_mismatch  # 방향은 보정, 실제는 보정 없음


def test_방향과_실제_보정이_같으면_어긋남_표시가_없다():
    out, _ = _run()
    assert "oa_1:29-2:c1" not in out.direction_amendment_mismatch


def test_사건_전체_답의_보정_설명_유무가_바깥_보정과_어긋나면_다시_부른다():
    transport = FakeTransport(
        {
            "f4.direction": [_answer("direction_inventive"), _answer("direction_clarity")],
            "f4.opinion_unit": [_resp(UNIT_OUT), _resp(UNIT_OUT)],
            "f4.opinion_case": [_resp(CASE_WITHOUT), _resp(CASE_WITH)],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    options = dataclasses.replace(load_f4_options(), amendment_enabled=False)
    out = run_f4(F4Input.model_validate(_case()), ctx=ctx, options=options)
    assert [c["step"] for c in transport.calls].count("f4.opinion_case") == 2
    assert OpinionKey.AMENDMENT in {s.key for s in out.drafts.opinion}


def test_항별_심사관_근거에_떨어진_줄은_확인_필요로_값_없는_줄은_빼고():
    _, t = _run()
    unit = [c for c in t.calls if c["step"] == "f4.opinion_unit"][0]["prompt"]
    assert "[0021]" in unit  # 확인된 줄
    assert "[0033]" in unit and "대조하지 못함" in unit  # 떨어진 줄 (값 남음)
    assert '"항": 3' not in unit.split("항별 심사관 근거")[1].split("##")[0]


def test_켜면_지금_동작_그대로():
    _, t = _run(enabled=True)
    steps = [c["step"] for c in t.calls]
    assert "f4.opinion_unit" not in steps and "f4.opinion_case" not in steps
    assert "f4.amendment" in steps and "f4.opinion" in steps


# ---- 11/26 골 모드 뒤 고침 (원인 표 work/opinion-goal-1126/followup_cause_table.md ②③④) ----


def test_합친_곳은_지운_항에만_적을_수_있다():
    import pytest
    from pydantic import ValidationError

    from patent_ai.core.f4_response_draft.inputs import ExternalClaimChange

    assert ExternalClaimChange(claim=3, change="deleted", merged_into=[1]).merged_into == [1]
    assert ExternalClaimChange(claim=3, change="deleted").merged_into == []
    with pytest.raises(ValidationError):
        ExternalClaimChange(claim=1, change="amended", after="글자", merged_into=[2])


MERGED = {
    "source": "보정서 접수번호 1",
    "claims": [
        {"claim": 1, "change": "amended", "after": AMENDED_1},
        {"claim": 3, "change": "deleted", "merged_into": [1]},
    ],
}


def test_코드_보정_표와_보정_결과에_합친_곳이_나온다():
    from patent_ai.core.f4_response_draft.opinion_v2 import amendment_rows, amendment_table

    inp = F4Input.model_validate(_case(MERGED))
    assert "- 제3항: 삭제 (제1항에 합침)" in amendment_table(inp)
    rows = json.loads(amendment_rows(inp))
    assert [r.get("합친 곳") for r in rows["바뀐 항"] if r["항"] == 3] == ["제1항"]


def test_묶음_범위_밖에서_바뀐_항은_다른_묶음으로_알린다():
    # 묶음 범위(2항)만 주면 1항 보정·3항 삭제를 모델이 "보정 결과에 없다"고 썼다
    from patent_ai.core.f4_response_draft.opinion_v2 import amendment_rows

    inp = F4Input.model_validate(_case(MERGED))
    rows = json.loads(amendment_rows(inp, [2]))
    assert rows["바뀐 항"] == []
    assert rows["바뀌지 않은 항"] == [2]
    assert rows["다른 묶음에서 바뀐 항"] == [
        {"항": 1, "바뀜": "보정"},
        {"항": 3, "바뀜": "삭제", "합친 곳": "제1항"},
    ]


def test_모델이_애매_표시한_줄도_값이_있으면_확인_필요로_싣는다():
    # 독립항 줄이 ambiguous(값 있음, check_failed 없음)라 빠져 모델이 "위치를 특정 안 했다"고 썼다
    from patent_ai.core.f4_response_draft.opinion_v2 import examiner_rows_v2

    data = _case()
    row = data["oa"]["claim_rows"][1]  # 1항 × 거절이유 1 (값 있음)
    row.pop("check_failed")
    row["status"] = {"value": "unverified", "reason": "ambiguous"}
    inp = F4Input.model_validate(data)
    unit = inp.units[0]  # 진보성, 1·2항
    rows = json.loads(examiner_rows_v2(inp, unit))
    amb = [r for r in rows if r["항"] == 1]
    assert amb and amb[0]["인용 위치"] == {"D1": ["[0033]"]}
    assert "대조하지 못함" in amb[0]["상태"]


# ---- 제출할 글에 내부 말이 섞이지 않게 (11/27 시연 전 화면 점검) ----
# 입력 JSON의 영어 키·코드 값(supported, initial, merged_into 등)을 모델이 글에 그대로 옮겼고,
# 검토 표시 [확인 필요]가 제출할 본문에 들어갔다
CODE_WORDS = (
    '"supported"', '"merged_into"', '"notice_kind"', '"changed_in_other_units"',
    '"initial"', '"deleted"', '"amended"', '"unit_id"',
)  # fmt: skip


def _run_units(unit_answers, case_out=CASE_WITH):
    transport = FakeTransport(
        {
            "f4.direction": [_answer("direction_inventive"), _answer("direction_clarity")],
            "f4.opinion_unit": [_resp(a) for a in unit_answers],
            "f4.opinion_case": [_resp(case_out)],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    options = dataclasses.replace(load_f4_options(), amendment_enabled=False)
    out = run_f4(F4Input.model_validate(_case(MERGED)), ctx=ctx, options=options)
    return out, transport


def test_의견서_입력에_영어_키와_코드_값을_넣지_않는다():
    _, t = _run(amendment=MERGED)
    for step in ("f4.opinion_unit", "f4.opinion_case"):
        prompt = [c for c in t.calls if c["step"] == step][0]["prompt"]
        assert [w for w in CODE_WORDS if w in prompt] == [], step


def test_글에_코드_값이나_확인_표시가_있으면_다시_부르고_확인_메모는_따로_칸에_모은다():
    bad = {
        "response": "거절이유 1은 supported=false입니다. 위치는 [0033]입니다 [확인 필요].",
        "checks": [],
    }
    good = {
        "response": "보정한 청구항 1은 인용발명 1과 다르다고 주장합니다.",
        "checks": ["[0033] 위치를 통지서 원문과 대조해 주세요"],
    }
    out, t = _run_units([bad, good, UNIT_OUT])
    assert [c["step"] for c in t.calls].count("f4.opinion_unit") == 3  # 첫 묶음만 한 번 더
    sections = {s.key: s.ai_text for s in out.drafts.opinion}
    body = sections[OpinionKey.RESPONSE]
    assert "[확인 필요]" not in body and "supported" not in body
    assert "[0033] 위치를 통지서 원문과 대조해 주세요" in sections[OpinionKey.REVIEW]
    assert [s.key for s in out.drafts.opinion][-1] == OpinionKey.REVIEW  # 맨 끝 칸


def test_다시_불러도_확인_표시가_남으면_표시만_지우고_묶음은_살린다():
    bad = {"response": "위치는 [0033]입니다 [확인 필요].", "checks": []}
    out, _ = _run_units([bad, bad, UNIT_OUT])
    body = {s.key: s.ai_text for s in out.drafts.opinion}[OpinionKey.RESPONSE]
    assert "위치는 [0033]입니다." in body and "[확인 필요]" not in body


def test_확인_메모가_없으면_확인_칸을_만들지_않는다():
    out, _ = _run_units([UNIT_OUT, UNIT_OUT])
    assert OpinionKey.REVIEW not in {s.key for s in out.drafts.opinion}


def test_대비_결과_입력의_코드_값을_한국어로_준다():
    # 대비 결과의 판정·출처 코드(difference_candidate, ai_found 등)를 모델이 확인 메모에 옮겨 썼다
    _, t = _run(amendment=MERGED)
    unit = [c for c in t.calls if c["step"] == "f4.opinion_unit"][0]["prompt"]
    for code in ('"difference_candidate"', '"disclosed"', '"ai_found"', '"examiner"'):
        assert code not in unit, code
    assert "차이점 후보" in unit and "같은 구성" in unit


def test_확인_메모는_같은_말을_한_번만_내부_코드는_한국어로_묶음마다_많아도_다섯_개():
    noisy = {
        "response": UNIT_OUT["response"],
        "checks": [
            "D1 [0041]은 대비 판정이 「unclear」였습니다. 확인해 주세요.",
            "D1 [0041]은 대비 판정이 「unclear」였습니다. 확인해 주세요.",
            "구성 1-1은 조회 범위(D1 상위 20 및 도면 설명)에서 확인되지 않았습니다.",
            *[f"확인할 점 {n}" for n in range(1, 7)],
        ],
    }
    out, _ = _run_units([noisy, UNIT_OUT])
    review = {s.key: s.ai_text for s in out.drafts.opinion}[OpinionKey.REVIEW]
    lines = review.splitlines()
    assert len(lines) == 5  # 묶음 하나에 많아도 다섯 줄
    assert sum("[0041]" in x for x in lines) == 1  # 같은 말은 한 번
    assert "unclear" not in review and "판단 어려움" in review
    assert "상위 20" not in review
