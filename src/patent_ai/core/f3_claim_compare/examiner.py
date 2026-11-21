"""심사관 지정 위치 -> 색인 조각 맞추기 (답이 정해진 코드 도구).

위치 글자는 F1이 정답 꼴로 맞춰 둔 값이다:
`[0016]`, `[0080]-[0081]`, `도 4c`, `청구항 9`, `요약`, `3:5-10`.
맞춤 규칙은 검색 계약 design 7-4의 인용문헌 판정과 같다 (채점기 코드는 import하지 않는다):
문단·범위는 겹치는 문단 조각, 도면은 그 도면 번호를 담은 조각,
청구항은 그 청구항 조각, 요약은 요약 조각.
못 맞추면 근거를 지어내지 않고 "확인되지 않음"으로 둔다.
"""

import re

from pydantic import BaseModel, ConfigDict

from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import ClaimRow, OAResult
from patent_ai.retrieval.schemas import Chunk

# F1이 만든 위치 값의 꼴 (해석이 아니라 정해진 코드 값 읽기)
_PARAGRAPH = re.compile(r"\[(\d{1,4})\](?:-\[(\d{1,4})\])?")
_FIGURE = re.compile(r"도 (\d+)[A-Za-z]?")
_CLAIM = re.compile(r"청구항 (\d+)")
_COLUMN_LINE = re.compile(r"\d+:\d+(?:-\d+)?")
_NO_LOCATION = "위치 없음"
_MAX_SAME_AS_HOPS = 5  # 같은 취지 줄을 따라가는 깊이 상한 (돌고 도는 것 막기)


class ExaminerMatch(BaseModel):
    """심사관이 짚은 위치 하나와 맞춘 조각."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    location: str  # F1 위치 값 그대로
    chunk_ids: list[str]  # 맞춘 조각 (chunk_id 오름차순). 못 맞추면 빈 목록
    status: Status


def match_location(location: str, chunks: list[Chunk]) -> ExaminerMatch:
    """위치 하나를 그 인용문헌의 조각들과 맞춘다. chunks는 그 문헌 조각만 넘긴다."""
    found: list[Chunk]
    if m := _PARAGRAPH.fullmatch(location):
        first = int(m.group(1))
        last = int(m.group(2) or m.group(1))
        found = [
            c
            for c in chunks
            if c.location.kind == "paragraph"
            and None not in (c.location.start, c.location.end)
            and c.location.start <= last
            and first <= c.location.end
        ]
    elif m := _FIGURE.fullmatch(location):
        found = [c for c in chunks if int(m.group(1)) in c.location.figures]
    elif m := _CLAIM.fullmatch(location):
        found = [c for c in chunks if int(m.group(1)) in c.location.claims]
    elif location == "요약":
        found = [c for c in chunks if c.chunk_kind == "abstract"]
    elif _COLUMN_LINE.fullmatch(location):
        # 칼럼·줄은 정렬 키가 없어 표기가 같은 조각만 맞음으로 본다
        found = [
            c for c in chunks if c.location.kind == "column_line" and c.location.label == location
        ]
    else:
        # 도면 부호만 짚은 것(`제어부(130)`) 등: 어느 문단인지 정할 수 없다
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS)
        return ExaminerMatch(location=location, chunk_ids=[], status=status)
    if not found:
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.EVIDENCE_REJECTED)
        return ExaminerMatch(location=location, chunk_ids=[], status=status)
    status = Status(value=StatusValue.CONFIRMED, checked="심사관 지정 위치를 색인 조각과 맞춤")
    return ExaminerMatch(
        location=location, chunk_ids=sorted(c.chunk_id for c in found), status=status
    )


def find_claim_row(oa: OAResult, rejection_no: int, claim: int) -> ClaimRow | None:
    """그 청구항 × 거절이유의 확인된 청구항 줄 (없으면 None)."""
    for row in oa.claim_rows:
        confirmed = row.status.value == StatusValue.CONFIRMED
        if confirmed and row.claim == claim and row.rejection == rejection_no:
            return row
    return None


def examiner_locations(oa: OAResult, rejection_no: int, claim: int, label: str) -> list[str]:
    """그 청구항 × 거절이유에서 심사관이 인용문헌 label에 짚은 위치 값들.

    순서: 그 청구항 줄의 위치 -> 같은 취지(same_as)로 가리킨 줄의 위치 -> 인용문헌 칸의 위치.
    `위치 없음 (...)`은 위치가 아니라 뺀다.
    """
    todo = [(rejection_no, claim)]
    seen: set[tuple[int, int]] = set()
    for _ in range(_MAX_SAME_AS_HOPS):
        if not todo:
            break
        rej_no, claim_no = todo.pop(0)
        if (rej_no, claim_no) in seen:
            continue
        seen.add((rej_no, claim_no))
        row = find_claim_row(oa, rej_no, claim_no)
        if row is None:
            continue
        if label in row.locations:
            return [x for x in row.locations[label] if not x.startswith(_NO_LOCATION)]
        for target in row.same_as:  # `claim:<n>` 또는 `rejection:<n>`
            kind, _, number = target.partition(":")
            todo.append((rej_no, int(number)) if kind == "claim" else (int(number), claim_no))
    # 청구항 줄에서 못 찾으면 거절이유의 인용문헌 칸
    for rej in oa.rejections:
        if rej.no != rejection_no:
            continue
        for c in rej.citations:
            confirmed = c.cited_paragraphs.status.value == StatusValue.CONFIRMED
            if c.label == label and confirmed:
                return list(c.cited_paragraphs.value or [])
    return []
