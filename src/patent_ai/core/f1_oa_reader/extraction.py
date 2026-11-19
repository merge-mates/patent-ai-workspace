"""모델이 돌려주는 출력 스키마 OAExtraction (design.md 3-2).

값마다 {value, raw_text, page, ambiguous}만 둔다. 상태·supported·country·flags는 없다:
상태는 원문 대조 결과라 코드가 정한다 (모델이 몰래 넣으면 검사에서 떨어짐).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class Item(BaseModel):
    """모델이 뽑은 값 하나. 원문 글자와 쪽을 같이 받는다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any | None = None
    raw_text: str | None = None
    page: int | None = None
    ambiguous: bool = False


class CitationExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: Item | None = None
    cited_paragraphs: Item | None = None  # 식별번호가 없으면 null


class RejectionExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    article: Item | None = None
    claims: Item | None = None
    citations: list[CitationExtraction] = []
    examiner_reasoning: Item | None = None  # value=요지, raw_text=원문


class RowCitationExtraction(BaseModel):
    """청구항 줄 안의 인용 하나: 어느 인용문헌을 어디로 짚었나 (모두 원문 글자)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str | None = None  # 모델이 붙인 라벨 (D1…). 코드가 거절이유 표의 라벨과 맞춰 봄
    number: Item | None = None  # 라벨 대신 인용 원문 (예: 인용발명 1)
    location: Item | None = None  # 짚은 위치 원문 (코드가 다시 읽음, value 안 씀)
    no_location: Item | None = None  # 위치 없음 표현 원문 (단순 부가, 설계 사항 등)


class ClaimRowExtraction(BaseModel):
    """청구항 줄 하나 (청구항 x 거절이유). 값은 전부 원문 글자이고 해석은 코드가 한다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: Item | None = None  # 청구항 번호 원문 (제5-7항이면 줄 셋으로 펼침)
    rejection: int | None = None  # 거절이유 표 순번
    citations: list[RowCitationExtraction] = []
    no_location: Item | None = None  # 인용이 하나도 없는 줄의 위치 없음 표현 원문 (설계 사항 등)
    same_as: list[Item] = []  # 같은 취지 대상 원문 (제1항과 동일한 취지, 1-1에서 본 바와 같이)
    clarity_terms: list[Item] = []  # 명확성 문제 표현 원문 (따옴표 안 글자)
    clarity_reason: str | None = None  # 참고용 한 구
    judgment: Item | None = None  # 이 줄 판단이 적힌 원문 글자·쪽


class OAExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    application_number: Item | None = None
    dispatch_number: Item | None = None
    examined_claims: Item | None = None  # 심사 대상 청구항 (원문 글자, 예: 제1항 내지 제20항)
    rejections: list[RejectionExtraction]
    allowable_claims: Item | None = None  # 칸이 없으면 null
    amendment_note: Item | None = None  # 칸이 없으면 null
    claim_rows: list[ClaimRowExtraction] = []  # 청구항 줄 (없으면 빈 목록)


# ---- 두 번째 답(재시도) 검사용 판 ----
# 모델이 재시도 안내를 받고도 목록 칸(same_as·clarity_terms)에 객체 대신 문자열을 넣는 경우가 있다
# (11/19 tune 5건 중 4건). 이때 실행 전체를 실패시키지 않으려고 두 번째 답만 이 판으로 검사한다.
# 문자열은 Item으로 바꾸지 않고 그대로 둔다.
# 원문·쪽이 없으니 claim_rows가 그 줄을 확인되지 않음으로 둔다.
class LooseClaimRowExtraction(ClaimRowExtraction):
    same_as: list[Item | str] = []  # type: ignore[assignment]
    clarity_terms: list[Item | str] = []  # type: ignore[assignment]


class LooseOAExtraction(OAExtraction):
    claim_rows: list[LooseClaimRowExtraction] = []  # type: ignore[assignment]
