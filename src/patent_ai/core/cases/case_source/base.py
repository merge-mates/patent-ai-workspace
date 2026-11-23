"""사건 자료 조회 인터페이스 (이슈 #54): 출원번호 + 발송번호 → 행정 이력·청구항 이력·출원서.

- 구현(받아 둔 폴더 `local_folder`, 2단계 KIPRIS)은 원본만 돌려준다. 자르기 전이어도 된다.
  OA 시점 자르기는 구현 밖 공통 코드(`cut.py`)가 늘 한다 (구현마다 다르게 자르지 않게).
- 글자는 KIPRIS Plus에서 받은 꼴: `¶`로 나눈 표, 첫 줄 머리글. KIPRIS 구현도 받은 응답을
  같은 꼴로 `data/raw/cases/<출원번호>/`에 두고 같은 파서(`parse.py`)를 쓴다.
- 못 가져온 것은 오류가 아니라 `Missing`(없음 + 이유)으로 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from patent_ai.core.schemas.common import UnverifiedReason

# 조회하는 자료 셋
MissingWhat = Literal["admin_history", "claim_history", "application_document"]


@dataclass(frozen=True)
class Missing:
    """가져오지 못한 자료 하나와 그 이유. detail에는 원문 글자를 넣지 않는다."""

    what: MissingWhat
    reason: UnverifiedReason
    detail: str


@dataclass(frozen=True)
class SourceFiles:
    """구현이 돌려주는 원본. 자료마다 값 또는 Missing."""

    admin_history: str | Missing  # 행정처리 이력 표 글자
    claim_history: str | Missing  # 청구항 변동 이력 표 글자
    application_document: Path | Missing  # 출원서(최초 명세서·출원 때 청구항) PDF


class CaseSource(Protocol):
    """사건 자료 조회 구현. 설정 `config/case_source.yaml`의 impl로 고른다."""

    name: str  # 단계 기록·로그에 남길 구현 이름 (예: local_folder)

    def fetch(self, application_number: str, dispatch_number: str) -> SourceFiles:
        """번호는 숫자만(하이픈 없음). 없는 자료는 Missing으로. 예외는 버그일 때만."""
        ...
