"""프롬프트 파일 읽고 $변수 채우기 (string.Template. JSON 중괄호는 그대로 둔다)."""

from pathlib import Path
from string import Template

from patent_ai.core.llm.errors import ModelConfigError


def render_prompt(prompt_path: str, variables: dict, root: Path) -> str:
    path = root / prompt_path
    if not path.is_file():
        raise ModelConfigError(f"프롬프트 파일이 없음: {path}")
    template = Template(path.read_text(encoding="utf-8"))
    # 잘못된 자리표시자(예: 홀로 쓴 $)는 거부
    if not template.is_valid():
        raise ModelConfigError(f"프롬프트에 잘못된 자리표시자가 있음: {prompt_path}")
    # 넘긴 변수 중 프롬프트에 없는 것은 헷갈림 방지로 거부
    extra = set(variables) - set(template.get_identifiers())
    if extra:
        raise ModelConfigError(f"프롬프트에 없는 변수: {sorted(extra)} ({prompt_path})")
    try:
        return template.substitute(variables)
    except (KeyError, ValueError) as e:
        raise ModelConfigError(f"프롬프트 변수가 빠짐: {e.args[0]} ({prompt_path})") from e
