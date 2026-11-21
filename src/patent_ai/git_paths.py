"""저장소 뿌리와 git 제외 검사 하나.

원본 데이터·결과 파일을 쓰기 전에 "그 경로가 커밋될 수 없는가"를 본다.
앱(retrieval)과 채점기(eval)가 같이 쓴다.
(eval은 patent_ai를 import할 수 있고, patent_ai는 eval을 import하지 않는다.)
"""

import subprocess
from pathlib import Path

# 저장소 뿌리 (src/patent_ai/git_paths.py 기준 두 단계 위)
REPO_ROOT = Path(__file__).resolve().parents[2]


def is_git_ignored(path: str | Path, *, outside_ok: bool = False) -> bool:
    """git이 무시하는 경로면 True.

    - 저장소 안: `git check-ignore -q`가 0이면 통과, 추적되거나 추적될 수 있으면 거절.
    - 저장소 밖: 기본은 거절 (git 제외인지 확인할 수 없으니 막는다). `outside_ok=True`면 통과
      (채점기 테스트처럼 tmp 폴더에 쓰는 경우).
    - 상대 경로는 지금 폴더 기준으로 푼다.
    """
    p = Path(path).resolve()
    try:
        p.relative_to(REPO_ROOT)
    except ValueError:
        return outside_ok
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--", str(p)],
        capture_output=True,
    )
    return r.returncode == 0
