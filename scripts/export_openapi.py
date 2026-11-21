"""FastAPI가 만든 OpenAPI를 docs/api/openapi.yaml로 쓴다 (손으로 고치지 않는다).

실행: uv run python scripts/export_openapi.py
라우터나 응답 모델을 바꾸면 다시 돌려 커밋한다 (tests/api/test_api_shapes.py가 어긋남을 잡는다).
"""

from pathlib import Path

import yaml

from patent_ai.api.main import create_app

OUT = Path(__file__).resolve().parents[1] / "docs/api/openapi.yaml"
HEADER = (
    "# 서버 코드가 만든 생성본이다. 손으로 고치지 않는다: uv run python scripts/export_openapi.py\n"
)


def render() -> str:
    spec = create_app().openapi()
    return HEADER + yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"썼다: {OUT}")
