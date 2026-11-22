"""`¶`로 나눈 KIPRIS Plus 표 읽기 (행정처리 이력, 청구항 변동 이력). 모든 구현이 같이 쓴다.

칸은 순서가 아니라 머리글 이름으로 읽는다. 꼭 쓰는 칸이 없으면 SourceFormatError.
원문 글자(청구항)는 그대로 둔다 (<br /> 줄바꿈 포함). 오류 메시지에는 원문을 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

SEP = "¶"

# 꼭 있어야 하는 칸
_ADMIN_COLUMNS = ("접수발송번호", "접수발송일자", "접수발송서류명")
_CLAIM_COLUMNS = ("접수발송번호", "청구항번호", "변경구분명", "청구항")


class SourceFormatError(ValueError):
    """표 꼴이 아니다 (머리글 없음, 꼭 쓰는 칸 없음)."""


@dataclass(frozen=True)
class AdminRow:
    """행정처리 이력 한 줄. 목록 순서 = 이력 순서."""

    number: str  # 접수발송번호 (숫자만)
    date: str  # 접수발송일자 (보이기용. 자르기에는 쓰지 않는다)
    name: str  # 접수발송서류명


@dataclass(frozen=True)
class ClaimChangeRow:
    """청구항 변동 이력 한 줄: 어느 접수가 몇 항을 어떻게 바꿨나."""

    receipt_number: str  # 그 변경을 만든 접수발송번호 (출원서·보정서)
    claim_no: str
    change: str  # 변경구분명 (신규·보정·삭제 등)
    text: str  # 청구항 원문


def _table(text: str, columns: tuple[str, ...], what: str) -> list[dict[str, str]]:
    lines = [ln for ln in text.lstrip("﻿").splitlines() if ln.strip()]
    if not lines:
        raise SourceFormatError(f"{what}: 머리글이 없음 (빈 파일)")
    header = [h.strip() for h in lines[0].split(SEP)]
    lacking = [c for c in columns if c not in header]
    if lacking:
        raise SourceFormatError(f"{what}: 칸이 없음 {lacking}")
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(SEP)]
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def parse_admin_history(text: str) -> list[AdminRow]:
    """행정처리 이력 표 → 줄 목록 (원래 순서 그대로)."""
    return [
        AdminRow(r["접수발송번호"], r["접수발송일자"], r["접수발송서류명"])
        for r in _table(text, _ADMIN_COLUMNS, "행정이력")
    ]


def parse_claim_history(text: str) -> list[ClaimChangeRow]:
    """청구항 변동 이력 표 → 줄 목록 (원래 순서 그대로)."""
    return [
        ClaimChangeRow(r["접수발송번호"], r["청구항번호"], r["변경구분명"], r["청구항"])
        for r in _table(text, _CLAIM_COLUMNS, "청구항이력")
    ]
