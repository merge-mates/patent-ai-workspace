"""로컬 인용문헌 폴더에서 사건이 가진 인용문헌 본문을 찾는다.

자동 조회(#54) 대신 모든 인용문헌 PDF를 로컬 폴더에 둔다:
`<root>/<출원번호>/<인용문헌 번호>.pdf` (예: data/raw/cited_v2/1020180022735/KR20140042531A.pdf).
폴더 위치는 인용문헌 색인 설정(config/cite_search.yaml raw_root)과 같은 곳을 쓴다.
여기 있는 인용문헌은 "받은 본문"으로 보고, 없는 것만 "올려 주세요"로 남긴다.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG = REPO_ROOT / "config" / "cite_search.yaml"


def local_citation_keys(case_number: str, root: Path) -> set[str]:
    """그 사건(출원번호) 폴더에 있는 인용문헌 PDF의 번호 키. 폴더가 없으면 빈 집합."""
    folder = root / case_number
    if not folder.is_dir():
        return set()
    # 파일 이름(확장자 뺀 것)이 인용문헌 번호 키다 (한국 공보 KR…A 꼴)
    return {p.stem for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"}


def configured_root() -> Path | None:
    """설정의 로컬 인용문헌 폴더. 설정이나 폴더가 없으면 None (경고만 남기고 로컬 확인을 안 함)."""
    try:
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except OSError:
        logger.warning("로컬 인용문헌: 설정 파일을 못 읽음 (%s)", CONFIG)
        return None
    raw = data.get("raw_root")
    if not raw:
        logger.warning("로컬 인용문헌: 설정에 raw_root가 없음 (%s)", CONFIG)
        return None
    root = Path(raw) if Path(raw).is_absolute() else REPO_ROOT / raw
    if not root.is_dir():
        logger.warning("로컬 인용문헌: 폴더가 없음 (%s)", root)
        return None
    return root


def configured_local_citations(case_number: str) -> set[str]:
    """앱에서 쓰는 기본: 설정 폴더에서 그 사건의 인용문헌 키를 찾는다."""
    root = configured_root()
    return local_citation_keys(case_number, root) if root is not None else set()
