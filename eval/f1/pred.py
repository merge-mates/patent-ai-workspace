"""F1 예측 꼴: 정답 꼴(gold.py)과 같은 칸이지만 값·쪽이 비어도 된다 (확인되지 않은 값).

OAResult -> 이 꼴 변환은 adapt.py(task 5)가 한다. 모르는 칸은 막아 변환 실수를 잡는다.
"""

from pydantic import BaseModel, ConfigDict, Field

from eval.f1.gold import Label, NoticeKind, RejectionKind, SameAs


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PValue(_P):
    value: str | None = None
    text: str | None = None
    page: int | None = None
    basis: str | None = None


class PDate(_P):
    text: str | None = None
    page: int | None = None


class PNoticeKind(_P):
    value: NoticeKind | None = None
    text: str | None = None
    page: int | None = None
    basis: str | None = None
    label: str | None = None


class PClaims(_P):
    value: list[int] | None = None
    text: str | None = None
    page: int | None = None
    basis: str | None = None


class PTargets(_P):
    value: list[int] | None = None
    text: str | None = None


class PRejection(_P):
    no: int
    kind: RejectionKind | None = None
    article: str | None = None
    supported: bool | None = None
    targets: PTargets = Field(default_factory=PTargets)
    page: int | None = None


class PCitation(_P):
    label: Label
    text: str | None = None
    key: str | None = None
    rejections: list[int] = Field(default_factory=list)
    page: int | None = None


class PClaimRow(_P):
    claim: int
    rejection: int
    citations: list[Label] = Field(default_factory=list)
    locations: dict[Label, list[str]] = Field(default_factory=dict)
    same_as: list[SameAs] = Field(default_factory=list)
    clarity_terms: list[str] = Field(default_factory=list)
    clarity_reason: str | None = None
    text: str | None = None  # 이 줄 판단 원문 글자 (원문 대조용, 정답에는 없음)
    page: int | None = None
    page_end: int | None = None


class F1Pred(_P):
    application_number: PValue = Field(default_factory=PValue)
    dispatch_number: PValue = Field(default_factory=PValue)
    notice_date: PDate = Field(default_factory=PDate)
    response_due: PDate = Field(default_factory=PDate)
    notice_kind: PNoticeKind = Field(default_factory=PNoticeKind)
    examined_claims: PClaims = Field(default_factory=PClaims)
    allowable_claims: PClaims = Field(default_factory=PClaims)
    amendment_note: PValue = Field(default_factory=PValue)
    rejections: list[PRejection] = Field(default_factory=list)
    citations: list[PCitation] = Field(default_factory=list)
    claim_rows: list[PClaimRow] = Field(default_factory=list)
