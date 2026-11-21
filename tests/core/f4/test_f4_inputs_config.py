"""F4 공용 뼈대 테스트: 입력 모델, 빈 법률 근거 묶음, 설정 읽기.

기대값은 구현 계획 C1과 `docs/features/F4/design.md`
3-1절(입력·빈 법률 근거)·7-2절(설정)에서 가져왔다.
"""

import json
import logging
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
    assert options.max_units >= 1 and options.max_candidates >= 1
    assert options.min_basis_chars >= 1  # 명세서 근거 글자 길이 하한
    # 묶음마다 첫 호출 + 다시 한 번
    assert cfg.max_model_calls == 2 * options.max_units


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "f4.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_저장소_설정은_최후거절이유_보정_제한_스위치가_기본으로_켜져_있다():
    assert load_f4_options().final_rejection_limit is True


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


_STEP = "  model: m\n  effort: medium\n  max_tokens: 1\n  prompt: p.md\n  max_model_calls: {n}\n"


@pytest.mark.parametrize("step", ["direction", "opinion", "amendment"])
def test_단계_호출_상한이_묶음_수의_두_배보다_작으면_멈춘다(tmp_path, step):
    top = "final_rejection_limit: false\nmax_units: 4\nmax_candidates: 2\nmin_basis_chars: 7\n"
    ok = _write(tmp_path, top + f"{step}:\n" + _STEP.format(n=8))
    assert load_f4_options(ok).max_units == 4  # 2 × 4 = 8은 통과
    with pytest.raises(ModelConfigError, match="max_model_calls"):
        load_f4_options(_write(tmp_path, top + f"{step}:\n" + _STEP.format(n=7)))


def test_설정_파일이_없으면_멈춘다(tmp_path):
    with pytest.raises(ModelConfigError):
        load_f4_options(tmp_path)


# ---- ④ 연결 키 (F4 design 3-1: unit_id → 거절이유 단위 → 빈 묶음 + 경고) ----
def _rejection_bundle(inp: F4Input, rejection: int, bundle_id: str) -> LegalEvidenceBundle:
    """F2가 거절이유 하나마다 만드는 묶음 (unit_id 없음, oa_id·rejection으로 잇는다)."""
    unit = next(u for u in inp.units if u.rejection == rejection)
    made = empty_legal_bundle(inp.oa.oa_id, unit, inp.checked_on)
    return made.model_copy(update={"bundle_id": bundle_id, "unit_id": None})


def test_unit_id가_같은_묶음을_거절이유_단위_묶음보다_먼저_쓴다():
    inp = _case()
    first = inp.units[0]
    by_unit = empty_legal_bundle(inp.oa.oa_id, first, inp.checked_on).model_copy(
        update={"bundle_id": "lb_unit"}
    )
    by_rejection = _rejection_bundle(inp, first.rejection, "lb_rej")
    with_legal = inp.model_copy(update={"legal": [by_rejection, by_unit]})
    assert legal_bundle_for(with_legal, first).bundle_id == "lb_unit"


def test_unit_id가_빈_묶음은_같은_OA_같은_거절이유의_모든_단위가_쓴다():
    inp = _case()
    first, second = inp.units  # 거절이유 1(진보성), 2(명확성)
    extra = first.model_copy(update={"unit_id": "oa_1:29-2:c3", "claims": [3], "order": 3})
    many = inp.model_copy(update={"units": [first, extra, second]})
    with_legal = many.model_copy(update={"legal": [_rejection_bundle(inp, 1, "lb_rej1")]})
    assert legal_bundle_for(with_legal, first).bundle_id == "lb_rej1"
    assert legal_bundle_for(with_legal, extra).bundle_id == "lb_rej1"


def test_다른_OA나_다른_거절이유의_묶음은_쓰지_않고_경고한다(caplog):
    inp = _case()
    first, second = inp.units
    other_oa = _rejection_bundle(inp, 1, "lb_other").model_copy(update={"oa_id": "oa_9"})
    with_legal = inp.model_copy(update={"legal": [_rejection_bundle(inp, 1, "lb_rej1"), other_oa]})
    with caplog.at_level(logging.WARNING):
        made = legal_bundle_for(with_legal, second)  # 거절이유 2 것이 없음
    assert made.bundle_id == f"lb:{second.unit_id}"
    assert made.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert second.unit_id in caplog.text
    only_other = inp.model_copy(update={"legal": [other_oa]})
    assert legal_bundle_for(only_other, first).bundle_id == f"lb:{first.unit_id}"


def test_법률_근거가_아예_없으면_경고_없이_빈_묶음(caplog):
    inp = _case()
    with caplog.at_level(logging.WARNING):
        made = legal_bundle_for(inp, inp.units[0])
    assert made.status.value == StatusValue.UNVERIFIED
    assert caplog.text == ""  # F2를 안 돌린 것은 지금 기본 상태라 경고하지 않는다
