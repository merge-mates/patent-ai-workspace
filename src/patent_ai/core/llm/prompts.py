"""프롬프트 파일 읽고 {변수} 채우기."""

from pathlib import Path

from patent_ai.core.llm.errors import ModelConfigError


def render_prompt(prompt_path: str, variables: dict, root: Path) -> str:
    path = root / prompt_path
    if not path.is_file():
        raise ModelConfigError(f"프롬프트 파일이 없음: {path}")
    template = path.read_text(encoding="utf-8")
    try:
        return template.format(**variables)
    except KeyError as e:
        raise ModelConfigError(f"프롬프트 변수가 빠짐: {e.args[0]} ({prompt_path})") from e
