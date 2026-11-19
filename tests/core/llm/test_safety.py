"""#13 리뷰 반영: 진짜 호출 막기·녹화 위치·프롬프트·설정 검사·캐시 규칙."""

import importlib.util
import logging
from pathlib import Path

import pytest

from patent_ai.core.llm import cache as cache_mod
from patent_ai.core.llm.cache import FileCache, MemoryCache, make_cache_key
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import CallBudget
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.transport import AnthropicTransport, FakeTransport, TransportResponse

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
VARS = {"lines": 2, "text": "본문"}
STEP = "test.summarize"


def call(transport, cache=None, variables=VARS, step=STEP, root=FIX, config_dir=FIX / "config"):
    return call_model(
        step,
        variables,
        None,
        "run-1",
        transport=transport,
        cache=cache,
        config_dir=config_dir,
        root=root,
        budget=CallBudget(),
    )


def fake():
    return FakeTransport({STEP: TransportResponse("답", 1000, 500)})


# ---- 2. 진짜 호출 막기 ----
def test_진짜_전송층은_테스트에서_만들_수_없다():
    with pytest.raises(RuntimeError, match="진짜 호출 막힘"):
        AnthropicTransport()


def test_transport_없이_call_model을_부르면_막힌다(tmp_path):
    # 호출 수 상한이 있어야 진짜 전송층을 만들러 간다 (없으면 그 전에 ModelConfigError)
    (tmp_path / "test.yaml").write_text(
        "summarize:\n  model: fake-model-1\n  temperature: 0.0\n  max_tokens: 256\n"
        "  prompt: prompts/summarize.txt\n  max_model_calls: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="진짜 호출 막힘"):
        call(None, cache=False, config_dir=tmp_path)


def test_키_환경_변수가_지워져_있다():
    import os

    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "OPENAI_API_KEY" not in os.environ


# ---- 3. 프롬프트: string.Template ----
def test_프롬프트_안_JSON_중괄호는_그대로_둔다():
    out = render_prompt("prompts/json_example.txt", {"text": "x"}, FIX)
    assert '{"title": "...", "score": 1}' in out
    assert "본문: x" in out


def test_프롬프트_변수가_빠지면_ModelConfigError():
    with pytest.raises(ModelConfigError, match="text"):
        render_prompt("prompts/summarize.txt", {"lines": 2}, FIX)


def test_프롬프트에_없는_변수를_넘기면_ModelConfigError():
    with pytest.raises(ModelConfigError, match="extra"):
        render_prompt("prompts/summarize.txt", {**VARS, "extra": 1}, FIX)


def test_잘못된_자리표시자는_ModelConfigError(tmp_path):
    (tmp_path / "p.txt").write_text("가격은 $ 입니다 $text", encoding="utf-8")
    with pytest.raises(ModelConfigError):
        render_prompt("p.txt", {"text": "x"}, tmp_path)


# ---- 4. 설정 검사 ----
def write_cfg(tmp_path, body):
    (tmp_path / "t.yaml").write_text(body, encoding="utf-8")
    return tmp_path


BASE = "  model: m\n  temperature: 0.0\n  max_tokens: 10\n  prompt: p.txt\n"
PRICES = "  price_per_mtok_input: 1\n  price_per_mtok_output: 2\n"


def test_가격이_하나만_있으면_ModelConfigError(tmp_path):
    d = write_cfg(tmp_path, "s:\n" + BASE + "  price_per_mtok_input: 1\n")
    with pytest.raises(ModelConfigError, match="price"):
        load_step_config("t.s", d)


def test_가격_값을_숫자로_못_바꾸면_ModelConfigError(tmp_path):
    d = write_cfg(
        tmp_path, "s:\n" + BASE + "  price_per_mtok_input: abc\n  price_per_mtok_output: 2\n"
    )
    with pytest.raises(ModelConfigError):
        load_step_config("t.s", d)


def test_temperature를_숫자로_못_바꾸면_ModelConfigError(tmp_path):
    d = write_cfg(tmp_path, "s:\n  model: m\n  temperature: hot\n  max_tokens: 10\n  prompt: p\n")
    with pytest.raises(ModelConfigError, match="temperature"):
        load_step_config("t.s", d)


def test_max_tokens가_비어_있으면_ModelConfigError(tmp_path):
    d = write_cfg(tmp_path, "s:\n  model: m\n  temperature: 0\n  max_tokens:\n  prompt: p\n")
    with pytest.raises(ModelConfigError, match="max_tokens"):
        load_step_config("t.s", d)


def test_YAML_최상위가_dict가_아니면_ModelConfigError(tmp_path):
    d = write_cfg(tmp_path, "- a\n- b\n")
    with pytest.raises(ModelConfigError):
        load_step_config("t.s", d)


def test_가격이_없으면_경고(tmp_path, caplog):
    d = write_cfg(tmp_path, "s:\n" + BASE)
    with caplog.at_level(logging.WARNING):
        load_step_config("t.s", d)
    assert "price" in caplog.text


def test_모르는_키는_경고_task3_키는_조용(tmp_path, caplog):
    d = write_cfg(
        tmp_path,
        "s:\n" + BASE + PRICES + "  max_model_calls: 3\n  max_input_tokens: 9\n  max_retries: 2\n",
    )
    with caplog.at_level(logging.WARNING):
        load_step_config("t.s", d)
    assert caplog.text == ""
    d = write_cfg(tmp_path, "s:\n" + BASE + PRICES + "  temprature: 1\n")
    with caplog.at_level(logging.WARNING):
        load_step_config("t.s", d)
    assert "temprature" in caplog.text


# ---- 5. 진짜 전송층이면 기본 파일 캐시 ----
def test_transport가_없으면_기본_FileCache를_쓴다(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", tmp_path / "default")
    call(fake(), cache=FileCache(tmp_path / "default"))  # 캐시를 채워 둔다
    r = call(None)  # transport·cache 모두 없음 -> 기본 캐시에서 적중, 진짜 전송층은 안 만듦
    assert r.from_cache is True


def test_fake_transport면_cache_기본은_캐시_안_씀():
    t = fake()
    call(t)
    call(t)
    assert len(t.calls) == 2


# ---- 6. 캐시 적중은 비용 0 ----
def test_캐시_적중이면_cost는_0이고_토큰은_저장값():
    c = MemoryCache()
    t = fake()
    first = call(t, c)
    second = call(t, c)
    assert first.cost == pytest.approx(0.0105)
    assert second.cost == 0.0
    assert (second.input_tokens, second.output_tokens) == (1000, 500)


# ---- 7. 캐시 키에 step, JSON 안 되는 변수 거부 ----
def test_캐시_키에_step이_들어간다():
    kw = dict(
        model="m",
        prompt_template="p",
        variables={},
        temperature=0.0,
        max_tokens=1,
        attempt=1,
    )
    assert make_cache_key(step="a.x", **kw) != make_cache_key(step="a.y", **kw)


def test_JSON으로_못_바꾸는_변수는_ModelConfigError():
    with pytest.raises(ModelConfigError):
        call(fake(), MemoryCache(), variables={"lines": {1, 2}, "text": "x"})


# ---- 1. 녹화 스크립트 ----
def load_script():
    spec = importlib.util.spec_from_file_location(
        "record_llm", REPO_ROOT / "scripts" / "record_llm.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_녹화_기본_폴더는_work_llm_recordings():
    assert load_script().DEFAULT_OUT == REPO_ROOT / "work" / "llm_recordings"


def test_data_아래_경로는_거부_판정():
    s = load_script()
    assert s.is_under_data_dir(REPO_ROOT / "data" / "raw" / "oa.json") is True
    assert s.is_under_data_dir(REPO_ROOT / "data" / "x.json") is True
    assert s.is_under_data_dir(REPO_ROOT / "data" / ".." / "tests" / "v.json") is False
    assert s.is_under_data_dir(REPO_ROOT / "tests" / "v.json") is False
    assert s.is_under_data_dir(REPO_ROOT / "database" / "v.json") is False


def test_data_아래_변수_파일이면_종료코드_1과_이유(capsys):
    s = load_script()
    code = s.main(["test.summarize", str(REPO_ROOT / "data" / "raw" / "oa.json")])
    assert code == 1
    assert "data/" in capsys.readouterr().err


def test_스크립트_도움말에_지어낸_통지서만_녹화한다고_적혀_있다():
    assert "지어낸" in load_script().__doc__


def test_메인_checkout의_data_아래도_거부(tmp_path):
    s = load_script()
    main_root = tmp_path / "main_checkout"
    roots = [REPO_ROOT, main_root]
    assert s.is_under_data_dir(main_root / "data" / "raw" / "oa.json", roots) is True
    assert s.is_under_data_dir(main_root / "tests" / "v.json", roots) is False


def test_data_대소문자가_달라도_거부(tmp_path):
    s = load_script()
    assert s.is_under_data_dir(REPO_ROOT / "DATA" / "x.json") is True
    assert s.is_under_data_dir(tmp_path / "Main" / "Data" / "x.json", [tmp_path / "main"]) is True


def test_git_공통_폴더의_부모를_메인_checkout으로_본다():
    s = load_script()
    roots = s.repo_roots(git_common_dir="/a/b/repo/.git")
    assert Path("/a/b/repo") in roots
    assert REPO_ROOT in roots


def test_기본_캐시_폴더는_테스트마다_임시_폴더(tmp_path):
    assert cache_mod.DEFAULT_CACHE_DIR.is_relative_to(tmp_path)
