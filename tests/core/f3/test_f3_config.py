"""F3 설정·입력 모델 테스트. 기대값은 구현 계획 "정한 것"과 F3 뼈대 설계 1·8절."""

import pytest

from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.schemas.common import Status, StatusValue


def test_config_f3_yaml의_스위치와_검색_값():
    settings = load_f3_settings()
    assert settings.impl == "split_search"
    assert settings.second_search is True
    assert settings.use_examiner_paragraphs is True
    assert settings.search.impl == "hybrid"
    assert settings.search.index_version == "cite-idx-v2"
    assert settings.search.k == 10
    assert settings.search.hybrid.rrf_k == 60
    assert settings.search.hybrid.weights == {"bm25": 0.5, "vector": 0.5}


def test_검색기에_넘길_settings에는_색인_판과_hybrid_칸이_있다():
    searcher_settings = load_f3_settings().search.searcher_settings()
    assert searcher_settings["index_version"] == "cite-idx-v2"
    assert searcher_settings["hybrid"] == {"rrf_k": 60, "weights": {"bm25": 0.5, "vector": 0.5}}
    assert "k" not in searcher_settings and "impl" not in searcher_settings


def test_split_elements_단계의_모델_설정():
    cfg = load_step_config("f3.split_elements")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-haiku-5-5", "medium", 64000)
    assert cfg.prompt == "prompts/f3/split_elements.md"
    assert cfg.max_model_calls is not None  # 진짜 전송층은 상한이 꼭 있어야 한다


def test_설정에_스위치가_빠지면_기본값으로_때우지_않고_멈춘다(tmp_path):
    (tmp_path / "f3.yaml").write_text("impl: split_search\n", encoding="utf-8")
    with pytest.raises(ModelConfigError):
        load_f3_settings(tmp_path)


def test_설정_파일이_없으면_멈춘다(tmp_path):
    with pytest.raises(ModelConfigError):
        load_f3_settings(tmp_path)


def test_F3Config는_dump했다가_다시_읽어도_같다():
    # 도구(Tool.run)가 입력을 model_dump → model_validate로 한 번 왕복시킨다
    inputs = F3Inputs(
        claims_at_oa={1: "화분에 있어서, 물통을 포함하는 화분.", 2: "제1항에 있어서, 받침."},
        claims_status=Status(value=StatusValue.CONFIRMED, checked="지어낸 청구항"),
        claims_document_id="d_claims",
        spec=None,
    )
    config = F3Config(settings=load_f3_settings(), inputs=inputs)
    assert F3Config.model_validate(config.model_dump()) == config
    assert F3Config.model_validate_json(config.model_dump_json()) == config
