"""단계 사이 입력 잇기: 앞 단계 결과 + 실행 입력(글자)에서 다음 단계 도구 입력을 만든다.

답이 정해진 코드다 (모델을 부르지 않는다). 입력을 못 만들면 값을 지어내지 않고
InputMissing으로 무엇이 없는지 돌려준다. 지휘는 그 단계를 "확인되지 않음"으로 넘긴다.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from patent_ai.core.f2_legal_research.run import F2Result, load_f2_settings
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.oa_result import OAResult


@dataclass(frozen=True)
class InputMissing:
    """단계 입력을 만들지 못한 이유 (그 단계는 돌리지 않는다)."""

    why: str


# 넘김 이유 글. 화면에 그대로 보이므로 코드 이름 대신 사람이 읽는 말로 쓴다 (이슈 #294)
NO_OA = "앞 단계인 OA 거절이유 정리 결과가 없음"
NO_F3 = "앞 단계인 청구항–인용발명 대비 결과가 없음"
NO_TEXTS = "OA 당시 청구항·명세서 글자를 찾지 못함"
NO_CHECKED_ON = "확인 기준일이 주어지지 않음"


def _missing(what: str) -> InputMissing:
    return InputMissing(f"input_unverified: {what}")


def f3_input(results: dict[str, Any], case_id: str, texts: F3Inputs | None) -> dict | InputMissing:
    """run_f3 입력: read_oa 결과(OAResult) + 실행 입력 글자 + config/f3.yaml 설정."""
    oa = results.get("read_oa")
    if not isinstance(oa, OAResult):
        return _missing(NO_OA)
    if texts is None:
        return _missing(NO_TEXTS)
    return {
        "oa_result": oa,
        # 사건 자료 목록은 자르기(#54)가 아직 CaseMaterials를 만들지 않아 빈 목록으로 넘긴다
        "case_materials": CaseMaterials(case_id=case_id),
        "config": {"settings": load_f3_settings(), "inputs": texts},
    }


def f2_input(results: dict[str, Any], checked_on: date | None) -> dict | InputMissing:
    """run_f2 입력: read_oa 결과(OAResult) + F3 판단 단위 + 확인 기준일 + config/f2.yaml 설정."""
    oa, f3 = results.get("read_oa"), results.get("run_f3")
    if not isinstance(oa, OAResult):
        return _missing(NO_OA)
    if not isinstance(f3, F3Result):
        # 법률 근거 묶음은 판단 단위마다 만든다 (F4가 unit_id로 찾음)
        return _missing(NO_F3)
    if checked_on is None:
        return _missing(NO_CHECKED_ON)
    return {
        "oa": oa,
        "units": f3.units,
        "checked_on": checked_on,
        "settings": load_f2_settings(),
    }


def f4_input(
    results: dict[str, Any], texts: F3Inputs | None, checked_on: date | None
) -> dict | InputMissing:
    """run_f4 입력: OAResult + F3 결과(판단 단위·대비표·명확성 검토) + 글자 + 확인 기준일."""
    oa, f3, f2 = results.get("read_oa"), results.get("run_f3"), results.get("run_f2")
    if not isinstance(oa, OAResult):
        return _missing(NO_OA)
    if not isinstance(f3, F3Result):
        return _missing(NO_F3)
    if texts is None:
        return _missing(NO_TEXTS)
    if checked_on is None:
        # 오늘 날짜를 코드가 몰래 읽지 않는다 (F4Input.checked_on과 같은 이유)
        return _missing(NO_CHECKED_ON)
    return {
        "oa": oa,
        "units": f3.units,
        "tables": f3.comparisons,
        "clarity": f3.clarity_reviews,
        # F3 보류: F4가 단위 안 보류(f3_compare:<unit_id>:claimN 등)를 그 묶음 후보에 표시한다
        "held_tasks": f3.held_tasks,
        # F2 결과. F2를 넘겼으면 비워 두고, F4가 묶음마다 "확인되지 않음" 빈 묶음을 쓴다
        "legal": f2.bundles if isinstance(f2, F2Result) else [],
        "claims_text": [
            {"claim": no, "text": text, "document_id": texts.claims_document_id}
            for no, text in sorted(texts.claims_at_oa.items())
        ],
        "spec": texts.spec,
        "checked_on": checked_on,
    }
