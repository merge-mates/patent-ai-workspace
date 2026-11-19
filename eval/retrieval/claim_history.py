"""OA 당시 청구항 복원 (design 3-1). 청구항이력·행정이력 파일만 읽는다.

규칙: 행정이력 줄 순서로 OA 발송번호 앞에 있는 접수번호의 청구항 변경(신규·수정·삭제)만
차례로 적용한다. 날짜로 자르지 않는다. 메시지에는 청구항 글자를 넣지 않는다.
"""

import re
from pathlib import Path

SEP = "¶"
OA_DOC_NAME = "의견제출통지서"


class OaNotFound(Exception):
    """OA 발송번호가 행정이력에 없다 (그 사건은 줄을 빼고 센다)."""


def expand_claims(spec: str) -> list[int]:
    """ "3-4,8" -> [3, 4, 8]. 거꾸로 범위나 숫자가 아닌 글자는 ValueError."""
    out: list[int] = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not m:
            raise ValueError("청구항 번호 꼴이 아니다")
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if hi < lo:
            raise ValueError("청구항 범위가 거꾸로다")
        out.extend(range(lo, hi + 1))
    return out


def _read_table(path: Path) -> list[dict[str, str]]:
    """'¶'로 나뉜 표(첫 줄 머리글)를 칸 이름 -> 값 dict 목록으로 읽는다."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        return []
    header = lines[0].split(SEP)
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split(SEP)
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def claims_at_oa_with_stats(
    claim_history_path: Path, admin_history_path: Path, oa_no: str
) -> tuple[dict[int, str], int, int]:
    """(청구항 번호 -> 글자, 적용 안 한 변경 수, 모르는 변경구분명이라 건너뛴 수).

    적용 안 한 변경 = 행정이력에 없는 접수의 변경.
    """
    admin = _read_table(admin_history_path)
    oa_idx = next(
        (
            i
            for i, r in enumerate(admin)
            if r["접수발송서류명"].strip() == OA_DOC_NAME and r["접수발송번호"].strip() == oa_no
        ),
        None,
    )
    if oa_idx is None:
        raise OaNotFound("OA 발송번호가 행정이력에 없다")

    # OA 앞 접수번호 -> 행정이력 줄 순서 (같은 번호는 처음 나온 줄)
    order: dict[str, int] = {}
    for i, r in enumerate(admin[:oa_idx]):
        order.setdefault(r["접수발송번호"].strip(), i)
    known_any = {r["접수발송번호"].strip() for r in admin}

    changes = []
    unmatched = 0
    for pos, r in enumerate(_read_table(claim_history_path)):
        no = r["접수발송번호"].strip()
        if no in order:
            changes.append((order[no], pos, r))
        elif no not in known_any:
            unmatched += 1  # 행정이력에 없는 접수: 적용 안 함
        # 행정이력에 있지만 OA 뒤: 조용히 적용 안 함 (정상)
    changes.sort(key=lambda t: (t[0], t[1]))  # 행정이력 순서, 같은 접수 안은 파일 순서

    claims: dict[int, str] = {}
    unknown_kind = 0
    for _, _, r in changes:
        n = int(r["청구항번호"])
        kind = r["변경구분명"].strip()
        if kind in ("신규", "수정"):
            claims[n] = r["청구항"].replace("<br />", "\n")
        elif kind == "삭제":
            claims.pop(n, None)
        else:
            # 신규·수정·삭제가 아닌 종류: 적용하지 않고 센다 (조용히 넘기면 질의가 옛 판이 된다)
            unknown_kind += 1
    return claims, unmatched, unknown_kind


def claims_at_oa(claim_history_path: Path, admin_history_path: Path, oa_no: str) -> dict[int, str]:
    """OA 당시 청구항 {번호: 글자}."""
    return claims_at_oa_with_stats(claim_history_path, admin_history_path, oa_no)[0]
