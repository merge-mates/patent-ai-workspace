"""F1 정답 파일 읽기와 형식 검사 (docs/evaluation/f1-oa-gold.md 4절).

정답 폴더 하나 = OA 한 통당 JSON 하나. 틀린 파일은 이유와 함께 EvalError로 멈춘다.
파일 이름에 출원번호가 있으므로 메시지에는 "정답 파일 N번째"와 칸 경로만 쓴다 (원문 글자 금지).
"""

import json
import logging
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from eval.common.errors import EvalError

logger = logging.getLogger(__name__)

RejectionKind = Literal["novelty", "inventive_step", "clarity", "other"]
NoticeKind = Literal["initial", "final", "unknown"]
Label = Annotated[str, Field(pattern=r"^D[1-9][0-9]*$")]
SameAs = Annotated[str, Field(pattern=r"^(claim|rejection):[1-9][0-9]*$")]

# 문단 표기는 4자리 하나 또는 범위 하나만 (2.4: `[0080-0081]` 꼴 안 씀)
_PARAGRAPH = re.compile(r"\[\d{4}\](-\[\d{4}\])?")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _NeedsBasis(_Strict):
    """원문에 글자가 없어 정한 값(page null)은 basis에 이유를 적는다 (4절 마지막 줄)."""

    @model_validator(mode="after")
    def _쪽이_없으면_basis(self):
        if self.page is None and not (getattr(self, "basis", None) or "").strip():
            raise ValueError("page가 없으면 basis(정한 이유)가 있어야 한다")
        return self


class IdField(_Strict):
    """출원번호·발송번호: 하이픈 없는 값 + 원문 글자."""

    value: str
    text: str
    page: int


class DateField(_Strict):
    """통지일·제출기일: 원문 글자만 둔다 (날짜를 확정하지 않음, 2.1)."""

    text: str
    page: int


class NoticeKindField(_NeedsBasis):
    value: NoticeKind
    text: str | None = None
    page: int | None = None
    basis: str | None = None
    label: str | None = None  # 통지 이름 전체 (예: 최초거절이유통지)


class ClaimsField(_NeedsBasis):
    value: list[int]
    text: str | None = None
    page: int | None = None
    basis: str | None = None


class NoteField(_NeedsBasis):
    value: str | None = None
    text: str | None = None
    page: int | None = None
    basis: str | None = None


class Reviewed(_Strict):
    by: str | None = None
    date: str | None = None
    method: str | None = None
    scope: str | None = None


class Targets(_Strict):
    value: list[int]
    text: str


class Rejection(_Strict):
    no: int = Field(ge=1)
    kind: RejectionKind
    article: str
    supported: bool
    targets: Targets
    page: int


class Citation(_Strict):
    label: Label
    text: str
    key: str
    rejections: list[int]
    page: int


class ClaimRow(_Strict):
    claim: int = Field(ge=1)
    rejection: int = Field(ge=1)
    citations: list[Label] = Field(default_factory=list)
    locations: dict[Label, list[str]] = Field(default_factory=dict)
    same_as: list[SameAs] = Field(default_factory=list)
    clarity_terms: list[str] = Field(default_factory=list)
    clarity_reason: str | None = None  # 참고용, 채점 안 함
    page: int
    page_end: int | None = None  # 판단이 다음 쪽까지 이어질 때 끝 쪽

    @field_validator("locations")
    @classmethod
    def _문단_꼴(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        # `[`로 시작하는 것만 엄격히 본다. 도면·청구항·요약·칼럼·논문·부호 꼴은 원문대로 받는다
        for locs in v.values():
            for loc in locs:
                if loc.startswith("[") and not _PARAGRAPH.fullmatch(loc):
                    raise ValueError("문단 꼴이 틀리다 ([0016] 또는 [0080]-[0081])")
        return v


class F1Gold(_Strict):
    gold_version: StrictInt
    source: Literal["oa_pdf"]
    reviewed: Reviewed
    application_number: IdField
    dispatch_number: IdField
    notice_date: DateField
    response_due: DateField
    notice_kind: NoticeKindField
    examined_claims: ClaimsField
    allowable_claims: ClaimsField
    amendment_note: NoteField
    rejections: list[Rejection]
    citations: list[Citation]
    claim_rows: list[ClaimRow]


def _cross_problems(g: F1Gold) -> list[str]:
    """칸끼리 서로 맞는지 본다. 문제마다 '칸 경로: 이유' 한 줄 (값 글자는 번호만)."""
    out: list[str] = []
    nos = [r.no for r in g.rejections]
    if len(set(nos)) != len(nos):
        out.append("rejections: 같은 거절이유 순번이 두 번 나온다")
    labels = [c.label for c in g.citations]
    if len(set(labels)) != len(labels):
        out.append("citations: 같은 라벨이 두 번 나온다")
    by_no = {r.no: r for r in g.rejections}

    for i, r in enumerate(g.rejections):
        # 지원 = 세 종류(신규성·진보성·명확성)면 예, 그 밖은 지원 안 함 (2.2)
        if r.supported != (r.kind != "other"):
            out.append(f"rejections.{i}: supported가 kind({r.kind})와 맞지 않다")
    for i, c in enumerate(g.citations):
        for n in c.rejections:
            if n not in by_no:
                out.append(f"citations.{i}.rejections: 없는 거절이유 {n}")

    for i, row in enumerate(g.claim_rows):
        p = f"claim_rows.{i}"
        rej = by_no.get(row.rejection)
        if rej is None:
            out.append(f"{p}.rejection: 없는 거절이유 {row.rejection}")
            continue
        if not rej.supported:
            out.append(f"{p}: 지원 안 하는 거절이유 {rej.no}에는 청구항 줄을 만들지 않는다")
        if row.claim not in rej.targets.value:
            out.append(f"{p}: 청구항 {row.claim}이 거절이유 {rej.no}의 대상에 없다")
        unknown = [lab for lab in row.citations if lab not in labels]
        if unknown:
            out.append(f"{p}.citations: 인용문헌 표에 없는 라벨 {', '.join(unknown)}")
        extra = [lab for lab in row.locations if lab not in row.citations]
        if extra:
            out.append(f"{p}.locations: 그 줄 인용에 없는 라벨 {', '.join(extra)}")
        if rej.kind == "clarity":
            if row.citations or row.locations:
                out.append(f"{p}: 명확성 줄에는 인용·위치를 두지 않는다")
        elif row.clarity_terms or row.clarity_reason is not None:
            out.append(f"{p}: 명확성이 아닌 줄에는 명확성 표현을 두지 않는다")
        for target in row.same_as:
            kind, n = target.split(":")
            if kind == "rejection" and int(n) not in by_no:
                out.append(f"{p}.same_as: 없는 거절이유를 가리킨다 ({target})")
            if kind == "claim" and int(n) not in g.examined_claims.value:
                out.append(f"{p}.same_as: 심사 대상이 아닌 청구항을 가리킨다 ({target})")
    return out


def _validation_lines(e: ValidationError) -> list[str]:
    # 입력 값은 빼고 칸 경로와 이유만 (pydantic msg에는 입력 값이 들어가지 않는다)
    lines = []
    for err in e.errors():
        path = ".".join(str(x) for x in err["loc"]) or "<전체>"
        lines.append(f"{path}: {err['msg']}")
    return lines


def load_f1_gold(folder: str | Path, expected_version: int) -> list[F1Gold]:
    """정답 폴더의 *.json을 파일 이름 순서로 읽어 검사한다. 하나라도 틀리면 멈춘다."""
    d = Path(folder)
    if not d.is_dir():
        raise EvalError("F1 정답 폴더가 없다")
    files = sorted(d.glob("*.json"))
    if not files:
        raise EvalError("F1 정답 파일이 0개다")

    golds: list[F1Gold] = []
    for i, f in enumerate(files, start=1):
        where = f"정답 파일 {i}번째"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise EvalError(f"{where}: JSON 문법이 틀리다") from None
        try:
            g = F1Gold.model_validate(data)
        except ValidationError as e:
            raise EvalError(f"{where}: " + "; ".join(_validation_lines(e)[:5])) from None
        if g.gold_version != expected_version:
            raise EvalError(
                f"{where}: gold_version이 다르다: 파일 {g.gold_version}, VERSION {expected_version}"
            )
        problems = _cross_problems(g)
        if problems:
            raise EvalError(f"{where}: " + "; ".join(problems[:5]))
        if not g.claim_rows:
            logger.warning("%s: 청구항 줄이 0개다", where)
        golds.append(g)
    return golds
