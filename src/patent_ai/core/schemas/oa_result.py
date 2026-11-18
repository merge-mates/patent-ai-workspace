"""OAResult(①): F1이 내는 OA 정리 결과. 모양의 기준은 docs/features/F1/design.md 3-2절.

status는 칸들에서 모은 값과 같아야 한다 (검사로 강제). 만드는 쪽은 status·evidence 없이
칸만으로 `build_rejection`·`build_oa_result`를 부르면 된다.
"""

import logging
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import (
    Evidence,
    ExtractedValue,
    Flag,
    Origin,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)

logger = logging.getLogger(__name__)

ALL_CHECKED = "모든 칸 원문 대조"  # 모두 confirmed일 때 결과 status의 checked
SUPPORTED_COUNTRIES = {"KR", "US"}  # 조회를 지원하는 나라 (product.md 3.2)


class NoticeKind(StrEnum):
    """통지 종류. 정답 형식(f1-oa-gold.md)과 같은 코드."""

    INITIAL = "initial"
    FINAL = "final"
    UNKNOWN = "unknown"  # 머리말을 못 읽음. 이때만 unverified


class RejectionKind(StrEnum):
    """거절이유 종류. 정답 형식(f1-oa-gold.md 4절 `kind`)과 같은 코드."""

    NOVELTY = "novelty"  # 신규성 29조 1항 1·2호
    INVENTIVE_STEP = "inventive_step"  # 진보성 29조 2항
    CLARITY = "clarity"  # 명확성 42조 4항 2호
    OTHER = "other"  # 그 밖, 조문을 모름


# 조문 코드 -> 종류 (규칙, 모델 안 씀)
_KIND_BY_ARTICLE = {
    "29-1-1": RejectionKind.NOVELTY,
    "29-1-2": RejectionKind.NOVELTY,
    "29-2": RejectionKind.INVENTIVE_STEP,
    "42-4-2": RejectionKind.CLARITY,
}


def kind_of_article(article: str | None) -> RejectionKind:
    """조문 코드(`29-2`, 호가 여럿이면 `29-1-1|29-1-2`)로 종류를 정한다.

    조문을 모르거나(None) 표에 없으면 other. 호가 여럿인데 종류가 섞이면 other.
    """
    kinds = {_KIND_BY_ARTICLE.get(p, RejectionKind.OTHER) for p in (article or "").split("|")}
    return kinds.pop() if len(kinds) == 1 else RejectionKind.OTHER


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str  # D1, D2… (OA에 나온 순서, 같은 문헌은 같은 라벨)
    # 값은 정답 형식의 키 꼴 (KR20990000001A, US1234567B2…). 꼴을 못 정하면 null + 애매
    number: ExtractedValue[str]
    # 나라: KR/US/JP… 또는 못 정하면 value null + unverified(ambiguous)
    country: ExtractedValue[str]
    country_supported: bool
    # 값 꼴: [0016], [0080]-[0081], 도 4c, 청구항 9, 요약, 3:5-10
    cited_paragraphs: ExtractedValue[list[str]]
    flags: list[Flag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _나라와_지원_여부가_맞아야_함(self) -> Citation:
        value = self.country.value
        # KR·US면 지원, 그 밖의 나라와 못 정한 경우(null)는 지원 안 함
        if self.country_supported != (value in SUPPORTED_COUNTRIES):
            raise ValueError("country_supported는 country가 KR·US일 때만 true")
        # 나라를 못 정했으면(null) 확인됨일 수 없다: unverified(ambiguous)
        if value is None and self.country.status.value == StatusValue.CONFIRMED:
            raise ValueError("country.value가 null이면 status는 confirmed일 수 없음")
        if not self.country_supported and Flag.NEEDS_HUMAN_REVIEW not in self.flags:
            raise ValueError("country_supported=false면 flags에 needs_human_review가 필요")
        return self

    def excluded_from_status(self) -> bool:
        """지원 안 하는 나라(값 있음)는 status를 나쁘게 하지 않는다 (flags로만).

        나라를 못 정한 것(null)은 빠지지 않는다: unverified가 그대로 들어간다.
        """
        return self.country.value is not None and not self.country_supported


class Rejection(ResultBase):
    """거절이유 하나. 청구항은 거절이유마다 따로 둔다 (합치지 않음)."""

    no: int  # OA 거절이유 표 순번 (1부터)
    kind: RejectionKind  # 조문에서 규칙으로 정함 (build_rejection이 채움)
    article: ExtractedValue[str]  # 호가 여럿이면 `29-1-1|29-1-2`
    supported: bool
    claims: ExtractedValue[list[int]]
    citations: list[Citation] = Field(default_factory=list)
    examiner_reasoning: ExtractedValue[str]

    @model_validator(mode="after")
    def _검사(self) -> Rejection:
        if not self.supported and Flag.NEEDS_HUMAN_REVIEW not in self.flags:
            raise ValueError("supported=false면 flags에 needs_human_review가 필요")
        if self.kind != kind_of_article(self.article.value):
            raise ValueError(f"kind {self.kind}가 조문 {self.article.value}에서 정한 값과 다름")
        expected = summarize_rejection_status(**self._status_fields())
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 칸을 모은 값 {expected.value}와 다름")
        return self

    def _status_fields(self) -> dict[str, Any]:
        """status를 모을 때 넘길 칸 (객체 그대로, dump하지 않음)."""
        return {k: getattr(self, k) for k in _REJECTION_FIELD_NAMES}


_SAME_AS_FORM = re.compile(r"(claim|rejection):[1-9]\d*")  # 같은 취지 대상 꼴


class ClaimRow(BaseModel):
    """청구항 줄 하나 = 청구항 x 거절이유 (정답 형식 2.4, 채점 단위).

    값은 원문 대조를 통과했을 때만 둔다. 대조에 떨어지면 status가 unverified이고 값은 비어 있다
    (청구항·거절이유 번호만 어느 줄인지 알리려고 남길 수 있음).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int | None  # OA 시점 청구항 번호 (못 읽으면 null + unverified)
    rejection: int | None  # Rejection.no
    citations: list[str] = Field(default_factory=list)  # 라벨. 결합이면 여럿
    # 라벨 -> 정답 꼴 위치. 위치 없음이면 ["위치 없음 (<OA 표현>)"], 짚지 않은 인용은 키 없음
    locations: dict[str, list[str]] = Field(default_factory=dict)
    same_as: list[str] = Field(default_factory=list)  # `claim:<n>`·`rejection:<n>`
    clarity_terms: list[str] = Field(default_factory=list)  # 명확성 줄의 문제 표현 (따옴표 안 글자)
    clarity_reason: str | None = None  # 참고용 한 구 (모델이 쓴 글, 원문 대조 안 함, 채점 밖)
    clarity_reason_origin: Origin | None = None  # 이유가 있으면 ai_generated
    raw_text: str | None = None  # 이 줄 판단이 적힌 원문 글자
    page: int | None = None
    status: Status

    @model_validator(mode="after")
    def _검사(self) -> ClaimRow:
        if self.page is not None and (self.raw_text is None or not self.raw_text.strip()):
            raise ValueError("page가 있으면 raw_text는 비어 있지 않아야 함")
        if any(not _SAME_AS_FORM.fullmatch(x) for x in self.same_as):
            raise ValueError("same_as는 `claim:<번호>`·`rejection:<번호>` 꼴")
        # 이유는 AI가 쓴 글이라 늘 그렇게 표시한다 (원문에서 뽑은 값과 구분)
        expected_origin = Origin.AI_GENERATED if self.clarity_reason is not None else None
        if self.clarity_reason_origin != expected_origin:
            raise ValueError(
                "clarity_reason이 있으면 clarity_reason_origin은 ai_generated, 없으면 null"
            )
        if set(self.locations) - set(self.citations):
            raise ValueError("locations의 라벨은 citations에 있어야 함")
        if self.status.value == StatusValue.CONFIRMED:
            if None in (self.claim, self.rejection, self.raw_text, self.page):
                raise ValueError("confirmed 줄은 청구항·거절이유 번호와 원문 글자·쪽이 있어야 함")
        elif self.status.value == StatusValue.UNVERIFIED:
            kept = (self.citations, self.locations, self.same_as, self.clarity_terms)
            has_values = (
                any(kept) or self.clarity_reason is not None or bool(self.raw_text) or self.page
            )
            if self.status.reason == UnverifiedReason.AMBIGUOUS:
                # 애매한 줄(예: 인용이 여럿인데 판단 원문에 인용 번호가 없음)은 값·원문·쪽을 남겨
                # 사람이 보게 한다 (ExtractedValue의 ambiguous 규칙과 같게). 어느 줄인지는 알아야 함
                if has_values and (self.claim is None or self.rejection is None):
                    raise ValueError("값을 남긴 애매한 줄은 청구항·거절이유 번호가 있어야 함")
            elif has_values:
                # 대조에 떨어진 줄은 값을 남기지 않는다 (지어내지 않음)
                raise ValueError("unverified 줄은 값·원문 글자·쪽을 비워 둬야 함 (애매 제외)")
        else:
            raise ValueError("청구항 줄 status는 confirmed 또는 unverified")
        return self


class ExaminerHints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowable_claims: ExtractedValue[list[int]]  # 「특허 가능한 청구항」. 칸이 없으면 값 []
    amendment_note: ExtractedValue[str]  # 【보정에 관한 참고사항】. 칸이 없으면 값 null


class OAResult(ResultBase):
    oa_id: str
    application_number: ExtractedValue[str]
    dispatch_number: ExtractedValue[str]
    notice_date: ExtractedValue[str]  # value는 비우고 raw_text만 (날짜 확정 안 함)
    response_due: ExtractedValue[str]  # 위와 같음
    notice_kind: ExtractedValue[NoticeKind]
    examined_claims: ExtractedValue[list[int]]  # 심사 대상 청구항 (`제1-20항` -> [1..20])
    examined_claim_version: ExtractedValue[str] | None = None  # F1은 안 채움 (#16·#54)
    examiner_hints: ExaminerHints
    rejections: list[Rejection] = Field(default_factory=list)
    claim_rows: list[ClaimRow] = Field(default_factory=list)  # 정답 형식 2.4 청구항 줄

    @model_validator(mode="after")
    def _모양_검사(self) -> OAResult:
        self._줄_검사()
        # 날짜·기한은 원문 글자만 둔다
        for name in ("notice_date", "response_due"):
            if getattr(self, name).value is not None:
                raise ValueError(f"{name}.value는 비워야 함 (원문 글자만)")
        # 통지 종류 unknown은 못 읽었다는 뜻이라 confirmed일 수 없다
        kind = self.notice_kind
        if kind.value == NoticeKind.UNKNOWN and kind.status.value != StatusValue.UNVERIFIED:
            raise ValueError("notice_kind=unknown이면 status는 unverified")
        # 저장된 status는 칸을 모은 값과 같아야 한다
        fields = {k: getattr(self, k) for k in _OA_FIELD_NAMES}
        expected = summarize_status(**fields)
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 칸을 모은 값 {expected.value}와 다름")
        return self

    def _줄_검사(self) -> None:
        """청구항 줄은 지원하는 거절이유만 가리키고, 명확성 줄과 그 밖의 줄은 칸이 다르다."""
        by_no = {r.no: r for r in self.rejections}
        for row in self.claim_rows:
            if row.rejection is None:
                continue
            rej = by_no.get(row.rejection)
            if rej is None:
                raise ValueError(f"청구항 줄이 없는 거절이유 {row.rejection}을 가리킴")
            if not rej.supported:
                raise ValueError("지원 안 하는 거절이유는 청구항 줄을 만들지 않음")
            if rej.kind == RejectionKind.CLARITY:  # 명확성 줄은 인용 대신 표현
                if row.citations or row.locations:
                    raise ValueError("명확성 줄에는 인용·위치를 두지 않음")
            elif row.clarity_terms or row.clarity_reason is not None:
                raise ValueError("명확성이 아닌 줄에는 명확성 표현을 두지 않음")


# status를 모을 때 쓰는 칸 이름. 모르는 이름은 summarize_*가 TypeError로 거부한다
_REJECTION_FIELD_NAMES = ("article", "claims", "citations", "examiner_reasoning")
_OA_FIELD_NAMES = (
    "oa_id",
    "application_number",
    "dispatch_number",
    "notice_date",
    "response_due",
    "notice_kind",
    "examined_claims",
    "examined_claim_version",
    "examiner_hints",
    "rejections",
    "claim_rows",
)


def _as(model: type, x: Any) -> Any:
    """dict로 들어온 칸은 모델로 바꿔 쓴다 (만드는 쪽이 dict를 그대로 넘겨도 되게)."""
    return model.model_validate(x) if isinstance(x, dict) else x


def summarize_rejection_status(
    *,
    article: ExtractedValue,
    claims: ExtractedValue,
    citations: list[Citation],
    examiner_reasoning: ExtractedValue,
) -> Status:
    """거절이유 하나의 status: 그 안 칸들 중 가장 나쁜 값 (칸만 받는다, status는 필요 없음).

    지원 안 하는 나라(값 있음) 인용문헌은 빼고, 나라를 못 정한 것은 늘 넣는다.
    """
    article, claims, examiner_reasoning = (
        _as(ExtractedValue, v) for v in (article, claims, examiner_reasoning)
    )
    statuses = [article.status, claims.status]
    for c in (_as(Citation, c) for c in citations):
        if not c.excluded_from_status():
            statuses += [c.number.status, c.country.status, c.cited_paragraphs.status]
    statuses.append(examiner_reasoning.status)
    return worst_status(statuses, ALL_CHECKED)


def _excluded(r: Rejection) -> bool:
    """결과 status 모으기에서 뺄 거절이유: 지원 표 밖인데 조문은 원문 대조로 확인된 것만."""
    return not r.supported and r.article.status.value == StatusValue.CONFIRMED


def summarize_status(
    *,
    oa_id: str = "",
    application_number: ExtractedValue,
    dispatch_number: ExtractedValue,
    notice_date: ExtractedValue,
    response_due: ExtractedValue,
    notice_kind: ExtractedValue,
    examined_claims: ExtractedValue,
    examiner_hints: ExaminerHints,
    rejections: list[Rejection],
    examined_claim_version: ExtractedValue | None = None,
    claim_rows: list[ClaimRow] | None = None,
) -> Status:
    """결과 전체 status: 칸들 중 가장 나쁜 값.

    순서: 식별 정보 -> 통지 -> 거절이유 -> 청구항 줄 -> 힌트.

    지원 안 하는 거절이유(supported=false)는 빼고 모은다. 거절이유가 0개면
    unverified(not_extracted)로 두고 경고를 남긴다.
    """
    application_number, dispatch_number, notice_date, response_due, notice_kind = (
        _as(ExtractedValue, v)
        for v in (application_number, dispatch_number, notice_date, response_due, notice_kind)
    )
    examined_claims = _as(ExtractedValue, examined_claims)
    examiner_hints = _as(ExaminerHints, examiner_hints)
    examined_claim_version = _as(ExtractedValue, examined_claim_version)
    if not rejections:
        upper = [
            application_number,
            dispatch_number,
            notice_date,
            response_due,
            notice_kind,
            examined_claims,
        ]
        if all(
            v.status.value == StatusValue.UNVERIFIED
            and v.status.reason == UnverifiedReason.INPUT_UNVERIFIED
            for v in upper
        ):  # 글자 층이 없어 못 읽은 것: 거절이유 0개 경고 없이 그 이유를 그대로
            return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)
        logger.warning("OAResult %s: 거절이유 0개 -> unverified(not_extracted)", oa_id)
        return worst_status([], ALL_CHECKED)
    statuses = [
        application_number.status,
        dispatch_number.status,
        notice_date.status,
        response_due.status,
        notice_kind.status,
        examined_claims.status,
    ]
    if examined_claim_version is not None:
        statuses.append(examined_claim_version.status)
    # 지원 안 하는 이유는 조문이 확인됨일 때만 뺀다. 조문을 모르면(unverified·conflict) 넣는다
    statuses += [r.status for r in rejections if not _excluded(r)]
    statuses += [_as(ClaimRow, row).status for row in claim_rows or []]
    statuses += [examiner_hints.allowable_claims.status, examiner_hints.amendment_note.status]
    return worst_status(statuses, ALL_CHECKED)


def _evidence_of(values: list[ExtractedValue], document_id: str) -> list[Evidence]:
    # 대조에 통과한 것(confirmed)이고 쪽이 있는 값만 근거로 둔다
    return [
        Evidence(document_id=document_id, page=v.page, raw_text=v.raw_text)
        for v in values
        if v.page is not None and v.status.value == StatusValue.CONFIRMED
    ]


def collect_evidence(result: Rejection | OAResult, document_id: str) -> list[Evidence]:
    """결과 단위 evidence: 쪽이 있는 값마다 {document_id, page, raw_text}."""
    if isinstance(result, Rejection):
        values = [result.article, result.claims, result.examiner_reasoning]
        for c in result.citations:
            values += [c.number, c.country, c.cited_paragraphs]
        return _evidence_of(values, document_id)
    values = [
        result.application_number,
        result.dispatch_number,
        result.notice_date,
        result.response_due,
        result.notice_kind,
        result.examined_claims,
        result.examiner_hints.allowable_claims,
        result.examiner_hints.amendment_note,
    ]
    if result.examined_claim_version is not None:
        values.append(result.examined_claim_version)
    found = _evidence_of(values, document_id)
    for r in result.rejections:  # 거절이유 안의 근거도 모은다
        found += collect_evidence(r, document_id)
    found += [  # 확인된 청구항 줄의 판단 원문
        Evidence(document_id=document_id, page=row.page, raw_text=row.raw_text)
        for row in result.claim_rows
        if row.page is not None and row.status.value == StatusValue.CONFIRMED
    ]
    return found


def _check_names(model: type[BaseModel], fields: dict[str, Any]) -> None:
    """모르는 칸 이름(또는 직접 넣은 status·evidence)은 TypeError."""
    # status·evidence·kind는 도우미가 칸에서 채운다 (kind는 OAResult에는 없는 이름)
    unknown = set(fields) - (set(model.model_fields) - {"status", "evidence", "kind"})
    if unknown:
        raise TypeError(f"{model.__name__}에 없는(또는 직접 못 넣는) 칸: {sorted(unknown)}")


def build_rejection(*, document_id: str, **fields: Any) -> Rejection:
    """status·evidence 없이 칸만으로 만든다. 둘은 여기서 칸에서 모아 채운다."""
    _check_names(Rejection, fields)
    summary = {k: fields[k] for k in _REJECTION_FIELD_NAMES if k in fields}
    article = _as(ExtractedValue, fields["article"]) if "article" in fields else None
    kind = kind_of_article(article.value if article is not None else None)
    draft = Rejection(**fields, kind=kind, status=summarize_rejection_status(**summary))
    return draft.model_copy(update={"evidence": collect_evidence(draft, document_id)})


def build_oa_result(*, document_id: str, **fields: Any) -> OAResult:
    """status·evidence 없이 칸만으로 만든다. 거절이유는 Rejection이나 칸 dict(여기서 만듦)."""
    _check_names(OAResult, fields)
    fields = {
        **fields,
        "rejections": [
            build_rejection(document_id=document_id, **r) if isinstance(r, dict) else r
            for r in fields.get("rejections", [])
        ],
        "claim_rows": [_as(ClaimRow, row) for row in fields.get("claim_rows", [])],
    }
    summary = {k: fields[k] for k in _OA_FIELD_NAMES if k in fields}
    draft = OAResult(**fields, status=summarize_status(**summary))
    return draft.model_copy(update={"evidence": collect_evidence(draft, document_id)})
