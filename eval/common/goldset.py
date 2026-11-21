"""정답 세트 버전 검사와 정답 파일 경로 (.claude/rules/eval.md: 버전이 다르면 비교하지 않는다)."""

from pathlib import Path, PurePath

from eval.common.errors import EvalError


def read_goldset_version(goldsets_root: str | Path) -> int:
    """data/goldsets/VERSION(정수)을 읽는다. 파일이 없거나 정수가 아니면 멈춘다."""
    version_file = Path(goldsets_root) / "VERSION"
    if not version_file.is_file():
        raise EvalError("정답 세트 VERSION 파일이 없다")
    try:
        return int(version_file.read_text().strip())
    except ValueError:
        raise EvalError("정답 세트 VERSION 파일이 정수가 아니다") from None


def check_goldset_version(goldsets_root: str | Path, expected: int) -> None:
    """data/goldsets/VERSION(정수)이 설정의 goldset_version과 같은지 본다. 다르면 멈춘다."""
    version = read_goldset_version(goldsets_root)
    if version != expected:
        raise EvalError(f"goldset_version이 다르다: 설정 {expected}, VERSION {version}")


def gold_path(goldsets_root: str | Path, goldset: str, rel: str) -> Path:
    """정답 파일 경로 <root>/<goldset>/<rel>. `..`·절대 경로로 세트 폴더 밖을 가리키면 멈춘다."""
    r = PurePath(rel)
    if r.is_absolute() or ".." in r.parts:
        raise EvalError("설정의 gold 경로가 세트 폴더 밖을 가리킨다 (절대 경로·.. 금지)")
    return Path(goldsets_root) / goldset / r
