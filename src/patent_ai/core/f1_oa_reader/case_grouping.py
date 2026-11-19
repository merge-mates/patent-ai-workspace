"""사건 자료 묶기 규칙 (#16): 번호 읽기·정규화, 같은 사건·같은 문서로 묶기, 심사 대상 판, 빠진 자료.

기준은 docs/features/F1/design.md 4절과 requirements 합격 기준 4·8.
출원번호 + 발송번호(OA) / 접수번호(보정서)로 묶고, 날짜만으로 합치지 않는다.
OA 시점 자르기는 여기서 하지 않는다 (고정 단계 cut_to_oa, #54).
"""

import re
from collections.abc import Callable
from typing import Literal

from patent_ai.core.f1_oa_reader.rules import (
    normalize_application_number,
    normalize_dispatch_number,
)
from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue, UnverifiedReason

# [가정] 접수번호 꼴: 1-1-YYYY-NNNNNNN-NN (하이픈은 있어도 없어도). 표본 보정서로 확인 (#22).
# 앞뒤에 숫자가 더 붙으면 다른 번호의 일부일 수 있어 인정하지 않는다.
_RECEIPT_BODY = r"(?<!\d)1-?1-?\d{4}-?\d{7}-?\d{2}(?!\d)"

NumberKind = Literal["application", "dispatch", "receipt"]


def normalize_receipt_number(text: str) -> str | None:
    """글자 속 접수번호를 하이픈 없는 숫자(15자리)로. 꼴이 아니면 None (지어내지 않는다)."""
    m = re.search(_RECEIPT_BODY, text)
    return m.group(0).replace("-", "") if m else None


# 번호 종류 → 정규화 함수. 출원번호·발송번호는 통지서 읽기(rules.py)와 같은 규칙을 쓴다.
_NORMALIZERS: dict[NumberKind, Callable[[str], str | None]] = {
    "application": normalize_application_number,
    "dispatch": normalize_dispatch_number,
    "receipt": normalize_receipt_number,
}


def read_number(kind: NumberKind, text: str | None) -> ExtractedValue[str]:
    """번호 글자 하나를 값으로 읽는다.

    - 꼴이 맞으면 confirmed, 값은 숫자만, raw_text는 원문 그대로.
    - 꼴이 틀리면 unverified(not_extracted), 값은 비우고 글자는 남긴다 (사람이 보게).
    - 글자가 없으면 unverified(not_extracted), 글자도 없음.
    """
    if text is None or not text.strip():
        return ExtractedValue[str](
            status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
        )
    value = _NORMALIZERS[kind](text)
    if value is None:
        return ExtractedValue[str](
            raw_text=text,
            status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
        )
    return ExtractedValue[str](
        value=value,
        raw_text=text,
        status=Status(value=StatusValue.CONFIRMED, checked=f"{kind} 번호 꼴 맞음"),
    )
