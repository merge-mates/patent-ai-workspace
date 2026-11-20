"""F4 공용 뼈대 테스트: 입력 모델, 빈 법률 근거 묶음, 설정 읽기.

기대값은 구현 계획 C1과 design_f4.md 1·7·8절에서 가져왔다.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.config import F4Options, load_f4_options
from patent_ai.core.f4_response_draft.inputs import (
    F4Input,
    empty_legal_bundle,
    legal_bundle_for,
)
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import (
    AsOfSource,
    LegalEvidenceBundle,
    LegalSourceKind,
    QuestionSource,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"


def _case() -> F4Input:
    return F4Input.model_validate_json((FIXTURES / "case_basic.json").read_text("utf-8"))


# ---- 입력 모델 ----
def test_입력은_JSON으로_왕복해도_같다():
    inp = _case()
    again = F4Input.model_validate(json.loads(inp.model_dump_json()))
    assert again == inp
    assert [c.claim for c in inp.claims_text] == [1, 2, 3]
    assert inp.spec is None and inp.checked_on == date(2099, 2, 1)


# ---- 빈 법률 근거 묶음 (F2 미연결) ----
def test_빈_법률_근거_묶음은_확인되지_않음이고_없다고_하지_않는다():
    inp = _case()
    unit = inp.units[0]
    bundle = empty_legal_bundle(inp.oa.oa_id, unit, inp.checked_on)
    assert isinstance(bundle, LegalEvidenceBundle)
    assert (bundle.unit_id, bundle.oa_id, bundle.rejection) == (unit.unit_id, "oa_1", 1)
    assert bundle.claims == [] and bundle.checked_on == date(2099, 2, 1)
    # F2를 안 돌렸으므로 "조회 범위 내 없음"이 아니라 확인되지 않음
    assert bundle.status.value == StatusValue.UNVERIFIED
    assert bundle.status.reason == UnverifiedReason.NOT_EXTRACTED
    q = bundle.question
    assert q.text == "거절이유 1 법률 근거 (F2 미연결)"
    assert q.source == QuestionSource.OA_REJECTION
    assert (q.as_of, q.as_of_source) == (None, AsOfSource.NONE)
    assert q.source_kinds == [LegalSourceKind.STATUTE, LegalSourceKind.GUIDELINE]


def test_입력에_법률_근거가_있으면_그것을_없으면_빈_묶음을_쓴다():
    inp = _case()
    first, second = inp.units
    given = empty_legal_bundle(inp.oa.oa_id, first, inp.checked_on).model_copy(
        update={"bundle_id": "lb_given"}
    )
    with_legal = inp.model_copy(update={"legal": [given]})
    assert legal_bundle_for(with_legal, first).bundle_id == "lb_given"
    made = legal_bundle_for(with_legal, second)  # 이 묶음 것은 없어 새로 만든다
    assert made.unit_id == second.unit_id and made.status.value == StatusValue.UNVERIFIED


# ---- 설정 ----
def test_저장소_설정의_방향_후보_단계_값():
    cfg = load_step_config("f4.direction")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-haiku-5-5", "medium", 64000)
    assert cfg.prompt == "prompts/f4/direction.md"
    options = load_f4_options()
    assert options.final_rejection_limit is False  # 기본은 끔 (동작은 C7)
    assert options.max_units >= 1 and options.max_candidates >= 1
    assert options.min_basis_chars >= 1  # 명세서 근거 글자 길이 하한
    # 묶음마다 첫 호출 + 다시 한 번
    assert cfg.max_model_calls == 2 * options.max_units


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "f4.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_설정_파일에서_스위치와_상한을_읽는다(tmp_path):
    config_dir = _write(
        tmp_path,
        "final_rejection_limit: true\nmax_units: 4\nmax_candidates: 2\nmin_basis_chars: 7\n",
    )
    assert load_f4_options(config_dir) == F4Options(
        final_rejection_limit=True, max_units=4, max_candidates=2, min_basis_chars=7
    )


@pytest.mark.parametrize(
    "body",
    [
        "final_rejection_limit: 'no'\nmax_units: 4\nmax_candidates: 2\n",  # 참·거짓이 아님
        "final_rejection_limit: false\nmax_units: 0\nmax_candidates: 2\n",  # 1보다 작음
        "final_rejection_limit: false\nmax_units: 4\nmax_candidates: true\n",  # 숫자가 아님
        "final_rejection_limit: false\nmax_units: 4\n",  # 칸이 빠짐
        "final_rejection_limit: false\nmax_units: 4\nmax_candidates: 2\n",  # 근거 글자 하한이 빠짐
    ],
)
def test_설정_값_형이_틀리면_멈춘다(tmp_path, body):
    with pytest.raises(ModelConfigError):
        load_f4_options(_write(tmp_path, body))


def test_설정_파일이_없으면_멈춘다(tmp_path):
    with pytest.raises(ModelConfigError):
        load_f4_options(tmp_path)
