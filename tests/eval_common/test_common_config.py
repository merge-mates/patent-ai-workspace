"""공통 실험 설정 읽기 (eval/common/config.py)."""

import pytest
from pydantic import Field

from eval.common.config import BaseEvalConfig, load_yaml_config
from eval.common.errors import EvalError

OK = """\
experiment: m1-i3-x-y
baseline: m1-i2-x-baseline
goldset: tune
goldset_version: 1
impl: jaea
settings:
  model: some-model
budget:
  max_usd: 2.0
"""


class _ExtraConfig(BaseEvalConfig):
    """기능 채점기가 공통 칸 위에 자기 칸을 더하는 모양."""

    k: list[int] = Field(min_length=1)


def _write(tmp_path, text, name="config.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_틀_설정을_읽고_모르는_키는_무시한다(tmp_path):
    cfg = load_yaml_config(_write(tmp_path, OK), BaseEvalConfig)
    assert cfg.experiment == "m1-i3-x-y"
    assert cfg.goldset == "tune"
    assert cfg.goldset_version == 1
    assert cfg.impl == "jaea"
    assert cfg.settings == {"model": "some-model"}


def test_기능_설정꼴의_칸도_같이_읽는다(tmp_path):
    cfg = load_yaml_config(_write(tmp_path, OK + "k: [5, 10]\n"), _ExtraConfig)
    assert cfg.k == [5, 10]


def test_파일이_없으면_실패(tmp_path):
    with pytest.raises(EvalError, match="없다: nope.yaml"):
        load_yaml_config(tmp_path / "nope.yaml", BaseEvalConfig)


def test_빈_파일이면_실패(tmp_path):
    with pytest.raises(EvalError, match="비었거나"):
        load_yaml_config(_write(tmp_path, ""), BaseEvalConfig)


def test_YAML_문법이_틀리면_파일_이름만_말한다(tmp_path):
    with pytest.raises(EvalError, match="bad.yaml") as e:
        load_yaml_config(_write(tmp_path, "a: [1, 2\nsecret-text", "bad.yaml"), BaseEvalConfig)
    assert "secret-text" not in str(e.value)


def test_칸이_틀리면_칸_이름만_말한다(tmp_path):
    bad = OK.replace("goldset_version: 1", "goldset_version: tune-f1-v0")
    with pytest.raises(EvalError, match="goldset_version") as e:
        load_yaml_config(_write(tmp_path, bad), BaseEvalConfig)
    assert "tune-f1-v0" not in str(e.value)


def test_빠진_칸이_있으면_실패(tmp_path):
    with pytest.raises(EvalError, match="impl"):
        load_yaml_config(_write(tmp_path, OK.replace("impl: jaea\n", "")), BaseEvalConfig)
