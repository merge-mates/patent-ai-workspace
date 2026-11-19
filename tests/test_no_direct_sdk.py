"""모델 SDK(anthropic·openai)는 core/llm/transport.py 안에서만 import한다 (모델 호출은 한 곳)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = ROOT / "src" / "patent_ai" / "core" / "llm" / "transport.py"
SDKS = {"anthropic", "openai"}


def sdk_imports(path: Path) -> list[int]:
    """파일에서 SDK를 import하는 줄 번호들. ast로 읽어 주석·문자열은 걸리지 않는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in ast.walk(tree):  # 함수 안 import도 잡는다
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] if node.level == 0 else []
        else:
            continue
        if any(n.split(".")[0] in SDKS for n in names):
            lines.append(node.lineno)
    return lines


def violations(*dirs: Path, allowed: Path | None = ALLOWED) -> list[str]:
    found = []
    for d in dirs:
        for f in sorted(d.rglob("*.py")):
            if f.resolve() == allowed:
                continue
            found += [f"{f}:{n}" for n in sdk_imports(f)]
    return found


def test_transport_밖에서_SDK를_import하지_않는다():
    assert (ROOT / "src").is_dir() and (ROOT / "scripts").is_dir()
    assert violations(ROOT / "src", ROOT / "scripts") == []


def test_일부러_넣은_가짜_파일은_잡아낸다(tmp_path):
    (tmp_path / "a.py").write_text("import anthropic\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from openai import OpenAI\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("def f():\n    import anthropic.types\n", encoding="utf-8")
    assert len(violations(tmp_path, allowed=None)) == 3


def test_주석과_문자열은_오탐하지_않는다(tmp_path):
    (tmp_path / "ok.py").write_text(
        '# import anthropic\nx = "from openai import x"\nimport json\n', encoding="utf-8"
    )
    assert violations(tmp_path, allowed=None) == []
