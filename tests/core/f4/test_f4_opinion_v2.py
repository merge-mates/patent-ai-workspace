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
    assert "deleted" in unit


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
    assert "[0033]" in unit and "확인 필요" in unit  # 떨어진 줄 (값 남음)
    assert '"claim": 3' not in unit.split("항별 심사관 근거")[1].split("##")[0]


def test_켜면_지금_동작_그대로():
    _, t = _run(enabled=True)
    steps = [c["step"] for c in t.calls]
    assert "f4.opinion_unit" not in steps and "f4.opinion_case" not in steps
    assert "f4.amendment" in steps and "f4.opinion" in steps
