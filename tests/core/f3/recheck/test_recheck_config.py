"""근거 다시 찾기 설정 테스트. 기대값은 구현 계획 m3-i2-309b task-3과 design.md 5절."""

import pytest
import yaml

from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.recheck.config import RecheckSettings, load_recheck_settings
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.schemas.common import Status, StatusValue

OK = Status(value=StatusValue.CONFIRMED, checked="테스트")


def _raw() -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / "recheck.yaml").read_text(encoding="utf-8"))


def _write(tmp_path, data: dict):
    text = yaml.safe_dump(data, allow_unicode=True)
    (tmp_path / "recheck.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_설정_파일의_기본_값은_끔이고_판정은_compare():
    s = load_recheck_settings()
    assert (s.recheck, s.recheck_judge, s.reflect, s.supervisor, s.spec_basis) == (
        "none",
        "compare",
        0,
        "code",
        "none",
    )
    assert (s.limits.tool_calls, s.limits.turns) == (8, 10)
    assert (s.search.k_max, s.search.snippet_chars) == (10, 160)
    assert (s.search.rewrite_k, s.search.rewrite_n) == (10, 3)


def test_RecheckSettings_기본값은_none이고_F3Config가_옛_호출_그대로_받는다():
    assert RecheckSettings().recheck == "none"
    config = F3Config(
        settings=load_f3_settings(),
        inputs=F3Inputs(claims_at_oa={1: "a"}, claims_status=OK, claims_document_id="d"),
    )
    assert config.recheck.recheck == "none"


def test_단계_칸_rewrite와_agent를_core_llm이_읽는다():
    rewrite = load_step_config("recheck.rewrite")
    agent = load_step_config("recheck.agent")
    assert (rewrite.model, rewrite.effort, rewrite.max_tokens) == (
        "claude-haiku-5-5",
        "medium",
        4000,
    )
    assert (agent.model, agent.effort, agent.max_tokens) == ("claude-haiku-5-5", "medium", 16000)
    assert rewrite.prompt == "prompts/recheck/rewrite.md"
    assert agent.prompt == "prompts/recheck/cite_agent.md"
    assert (rewrite.max_model_calls, agent.max_model_calls) == (200, 400)
    assert rewrite.price_per_mtok_input == 0.10 and rewrite.price_per_mtok_output == 0.50
    assert (REPO_ROOT / rewrite.prompt).is_file() and (REPO_ROOT / agent.prompt).is_file()


@pytest.mark.parametrize(
    "missing",
    ["recheck", "recheck_judge", "reflect", "supervisor", "spec_basis", "limits", "search"],
)
def test_설정_칸이_빠지면_기본값으로_때우지_않고_멈춘다(tmp_path, missing):
    data = _raw()
    del data[missing]
    with pytest.raises(ModelConfigError):
        load_recheck_settings(_write(tmp_path, data))


def test_설정_파일이_없으면_멈춘다(tmp_path):
    with pytest.raises(ModelConfigError):
        load_recheck_settings(tmp_path)


@pytest.mark.parametrize(
    "key,value",
    [("reflect", 1), ("supervisor", "llm"), ("spec_basis", "fixed_loop"), ("spec_basis", "agent")],
)
def test_아직_구현_안_된_값은_조용히_무시하지_않고_멈춘다(tmp_path, key, value):
    data = _raw()
    data[key] = value
    with pytest.raises(ModelConfigError):
        load_recheck_settings(_write(tmp_path, data))


@pytest.mark.parametrize(
    "key,value",
    [("recheck", "fixed_loop"), ("recheck", "agent"), ("recheck_judge", "agent")],
)
def test_켤_수_있는_값은_받는다(tmp_path, key, value):
    data = _raw()
    data[key] = value
    assert getattr(load_recheck_settings(_write(tmp_path, data)), key) == value


def test_모르는_값은_멈춘다(tmp_path):
    data = _raw()
    data["recheck"] = "mystery"
    with pytest.raises(ModelConfigError):
        load_recheck_settings(_write(tmp_path, data))
