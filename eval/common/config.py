"""실험 설정(config.yaml) 읽기. 공통 칸만 두고, 기능 채점기는 이 꼴을 물려받아 칸을 더한다."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.common.errors import EvalError


class BaseEvalConfig(BaseModel):
    # 모르는 키는 막지 않는다: 틀의 baseline·budget 등이 같이 들어 있다
    model_config = ConfigDict(extra="ignore")

    experiment: str
    goldset: str  # tune / report
    goldset_version: int  # data/goldsets/VERSION과 같아야 한다
    impl: str  # 같은 인터페이스 뒤의 구현 이름
    settings: dict = Field(default_factory=dict)  # 구현에 그대로 넘김


def load_yaml_config[C: BaseEvalConfig](path: str | Path, config_cls: type[C]) -> C:
    """YAML을 읽어 config_cls로 검사한다. 틀리면 파일 이름·칸 이름만 담은 EvalError."""
    p = Path(path)
    if not p.is_file():
        raise EvalError(f"설정 파일이 없다: {p.name}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        # 원인 글자는 찍지 않고 파일 이름만
        raise EvalError(f"설정 파일 YAML 문법이 틀리다: {p.name}") from None
    if not isinstance(data, dict):
        raise EvalError(f"설정 파일이 비었거나 모양이 틀리다: {p.name}")
    try:
        return config_cls.model_validate(data)
    except ValidationError as e:
        names = sorted({str(err["loc"][0]) for err in e.errors() if err["loc"]})
        raise EvalError(f"설정 파일 칸이 틀리다: {', '.join(names)}") from None
