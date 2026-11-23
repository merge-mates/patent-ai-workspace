"""받아 둔 폴더 구현 (이슈 #54 1단계): `<root>/<출원번호>/<발송번호>/`의 파일을 읽는다.

폴더 꼴은 scripts/split_cases_at_oa.py가 만든 것 (docs/data/oa-eval-cases.md 2.3절):
  <출원번호>_행정이력.txt, <출원번호>_청구항이력.txt, <출원번호>_출원서_<접수번호>.pdf
이 폴더는 이미 OA 시점까지 잘려 있지만, 자르기는 공통 코드(cut.py)가 다시 한다 (구현을 믿지 않음).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from patent_ai.core.cases.case_source.base import CaseSource, Missing, SourceFiles
from patent_ai.core.schemas.common import UnverifiedReason
from patent_ai.git_paths import REPO_ROOT

DEFAULT_CONFIG = REPO_ROOT / "config" / "case_source.yaml"


class LocalFolderSource:
    name = "local_folder"

    def __init__(self, root: Path) -> None:
        self._root = root

    def _text(self, path: Path, what) -> str | Missing:
        if not path.is_file():
            return Missing(what, UnverifiedReason.LOOKUP_FAILED, f"받아 둔 폴더에 {path.name} 없음")
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            return Missing(
                what, UnverifiedReason.NOT_EXTRACTED, f"{path.name} 못 읽음 ({type(e).__name__})"
            )

    def fetch(self, application_number: str, dispatch_number: str) -> SourceFiles:
        folder = self._root / application_number / dispatch_number
        if not folder.is_dir():
            why = "받아 둔 폴더에 이 OA가 없음"
            return SourceFiles(
                Missing("admin_history", UnverifiedReason.LOOKUP_FAILED, why),
                Missing("claim_history", UnverifiedReason.LOOKUP_FAILED, why),
                Missing("application_document", UnverifiedReason.LOOKUP_FAILED, why),
            )
        filings = sorted(folder.glob(f"{application_number}_출원서_*.pdf"))
        if len(filings) == 1:
            document: Path | Missing = filings[0]
        elif not filings:
            document = Missing(
                "application_document", UnverifiedReason.LOOKUP_FAILED, "받아 둔 폴더에 출원서 없음"
            )
        else:
            document = Missing(
                "application_document",
                UnverifiedReason.AMBIGUOUS,
                "받아 둔 폴더에 출원서가 둘 이상",
            )
        return SourceFiles(
            self._text(folder / f"{application_number}_행정이력.txt", "admin_history"),
            self._text(folder / f"{application_number}_청구항이력.txt", "claim_history"),
            document,
        )


def load_case_source(config_path: Path = DEFAULT_CONFIG) -> CaseSource:
    """설정의 impl로 구현을 고른다. 모르는 impl이면 ValueError (조용히 다른 구현을 쓰지 않음)."""
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    impl = cfg.get("impl")
    if impl == "local_folder":
        root = Path(cfg.get("root") or "")
        if not str(root) or str(root) == ".":
            raise ValueError("case_source: local_folder에는 root가 있어야 함")
        return LocalFolderSource(root if root.is_absolute() else REPO_ROOT / root)
    raise ValueError(f"case_source: 모르는 impl {impl!r}")
