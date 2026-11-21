"""F2 근거 검토 정답 읽기와 형식 검사. 모양의 기준은 docs/evaluation/f2-evidence-gold.md.

파일 하나(<세트>/f2/evidence_cases.jsonl)에 한 줄 = 사례 하나. `kind`로 둘로 나뉜다.
  real     실제 질문: F2 조사 출력을 채점한다.
  injected 오류 주입: 근거 검토가 잘못된 근거를 잡고 고치는지 채점한다.
오류 메시지에는 줄 번호·칸 경로·오류 종류만 쓴다 (정답 글자를 싣지 않는다).

확인: uv run python -m eval.f2.gold --check data/goldsets/tune/f2/evidence_cases.jsonl
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eval.common.errors import EvalError
from eval.common.goldset import read_goldset_version
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.legal_evidence import (
    LegalEvidenceBundle,
    LegalQuestion,
    LegalSourceKind,
    QuestionSource,
    TextKind,
)

logger = logging.getLogger(__name__)

ErrorKind = Literal[
    "nonexistent_source",  # 없는 출처
    "claim_text_mismatch",  # 주장-원문 불일치
    "other_edition_asserted",  # 다른 시점 판본을 적용으로 단정
    "summary_as_full",  # 요지만 보고 전문이라 씀
    "old_deadline_as_current",  # 개정 전 기한을 현행처럼
]
ERROR_KINDS: tuple[str, ...] = (
    "nonexistent_source",
    "claim_text_mismatch",
    "other_edition_asserted",
    "summary_as_full",
    "old_deadline_as_current",
)


class NoGold(EvalError):
    """정답 파일이 없거나 비었다. 채점 실패가 아니라 "정답 없음"이다 (F4와 같은 뜻)."""


class Reviewed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str | None
    date: str | None


class ExpectedSource(BaseModel):
    """실제 질문이 찾아야 할 근거 하나."""

    model_config = ConfigDict(extra="forbid")

    source_kind: LegalSourceKind
    identifier: str  # 예: "특허법 제29조제2항"
    document_id: str  # 판본 문서 ID = 색인 doc_id
    loc: int | None  # 조문 6자리 위치 번호
    edition_status: Literal["confirmed", "unverified"]


class ExpectedFix(BaseModel):
    """주입된 오류의 고친 정답. null인 칸은 "그 칸은 안 따짐"."""

    model_config = ConfigDict(extra="forbid")

    identifier: str | None = None
    document_id: str | None = None
    text_kind: TextKind | None = None
    raw_text_contains: str | None = None

    @model_validator(mode="after")
    def _하나는_채운다(self) -> ExpectedFix:
        if all(
            v is None
            for v in (self.identifier, self.document_id, self.text_kind, self.raw_text_contains)
        ):
            raise ValueError("fix의 칸이 모두 null (고칠 정답이 없으면 fix 자체를 null로)")
        return self


class _CaseBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gold_version: int
    case_id: str
    reviewed: Reviewed

    @model_validator(mode="after")
    def _case_id가_있다(self) -> _CaseBase:
        if not self.case_id.strip():
            raise ValueError("case_id가 비어 있음")
        return self


class RealCase(_CaseBase):
    kind: Literal["real"]
    oa_id: str  # 발송번호
    rejection: int = Field(ge=1)
    question: LegalQuestion
    expect_sources: list[ExpectedSource] = Field(min_length=1)

    @model_validator(mode="after")
    def _OA_질문이고_기준일이_있다(self) -> RealCase:
        if self.question.source != QuestionSource.OA_REJECTION:
            raise ValueError("question.source는 oa_rejection")
        if self.question.as_of is None:
            raise ValueError("question.as_of가 필수 (판본을 가르려면 기준일이 있어야 함)")
        return self


class InjectedCase(_CaseBase):
    kind: Literal["injected"]
    error: ErrorKind
    base_case_id: str | None  # 망가뜨린 바탕 실제 질문 사례
    bundle: LegalEvidenceBundle  # 검토 전 모양
    target_claim: int  # bundle.claims[].no
    target_source: int = Field(ge=0)  # 그 주장 sources 순번
    fix: ExpectedFix | None

    @model_validator(mode="after")
    def _주입_모양(self) -> InjectedCase:
        claim = next((c for c in self.bundle.claims if c.no == self.target_claim), None)
        if claim is None:
            raise ValueError("target_claim이 bundle 주장에 없음")
        if self.target_source >= len(claim.sources):
            raise ValueError("target_source가 주장의 근거 순번 밖")
        # 검토 전 모양: 아직 아무 주장도 검토되지 않았다
        if any(c.review is not None for c in self.bundle.claims):
            raise ValueError("bundle은 검토 전 모양 (review 없음)")
        target = claim.sources[self.target_source]
        # 주입된 근거는 겉으로 멀쩡해 보여야 한다 (그래서 검토가 잡아야 의미가 있다)
        if target.status.value != StatusValue.CONFIRMED:
            raise ValueError("target 근거 status는 confirmed")
        self._종류별_일관성(target)
        return self

    def _종류별_일관성(self, target) -> None:
        fix, err = self.fix, self.error
        if err in ("nonexistent_source", "claim_text_mismatch"):
            if fix is not None:
                raise ValueError(f"{err}는 fix가 null")
        elif err == "summary_as_full":
            if target.source_kind not in (LegalSourceKind.PRECEDENT, LegalSourceKind.TRIAL):
                raise ValueError("summary_as_full은 판례·심결 근거")
            if target.text_kind != TextKind.FULL:
                raise ValueError("summary_as_full의 target text_kind는 full")
            if fix is None or fix.text_kind != TextKind.SUMMARY:
                raise ValueError("summary_as_full의 fix.text_kind는 summary")
        elif err == "old_deadline_as_current":
            if self.bundle.question.as_of is not None:
                raise ValueError("old_deadline_as_current는 현행 질문 (question.as_of가 null)")
            if fix is None or fix.document_id is None or fix.raw_text_contains is None:
                raise ValueError(
                    "old_deadline_as_current의 fix는 document_id·raw_text_contains 필수"
                )
        elif err == "other_edition_asserted":
            if fix is None or fix.document_id is None:
                raise ValueError("other_edition_asserted의 fix.document_id가 필수")
            if fix.document_id == target.evidence.document_id:
                raise ValueError("fix.document_id가 target 근거의 문서와 같음")


Case = Annotated[RealCase | InjectedCase, Field(discriminator="kind")]


class _Line(BaseModel):
    case: Case


def _lines(e: ValidationError) -> list[str]:
    """검사 오류를 칸 경로와 이유만으로 (입력 값 글자는 싣지 않는다)."""
    out = []
    for err in e.errors():
        path = ".".join(str(x) for x in err["loc"][1:])  # 맨 앞은 감싼 칸 이름
        line = f"{path or '(줄)'}: {err['type']}"
        # value_error의 msg는 대개 검사 코드에 박힌 고정 문구라 같이 싣는다.
        # 다만 core 스키마 중에는 입력 값을 msg에 넣는 검사도 있다 (예: unit_id 꼴 검사).
        # 입력 값(글자)이 msg 안에 들어 있으면 정답 글자가 새지 않게 msg를 빼고 type만 남긴다.
        # 그 밖의 오류는 msg에 입력 값이 낄 수 있어 type만 남긴다.
        if err["type"] == "value_error":
            msg = err["msg"].removeprefix("Value error, ")
            value = err.get("input")
            if not (isinstance(value, str) and value.strip() and value in msg):
                line += " (" + msg + ")"
        out.append(line)
    return out


def load_f2_cases(path: str | Path, expected_version: int) -> list[RealCase | InjectedCase]:
    """줄마다 읽고 검사한다. 파일이 없거나 0줄이면 NoGold, 하나라도 틀리면 EvalError."""
    p = Path(path)
    if not p.is_file():
        raise NoGold("F2 정답 파일이 없다")
    cases: list[RealCase | InjectedCase] = []
    seen: set[str] = set()
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue  # 빈 줄은 건너뜀
        where = f"정답 {n}번째 줄"
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            raise EvalError(f"{where}: JSON 문법이 틀리다") from None
        try:
            case = _Line.model_validate({"case": data}).case
        except ValidationError as e:
            raise EvalError(f"{where}: " + "; ".join(_lines(e)[:5])) from None
        if case.gold_version != expected_version:
            raise EvalError(
                f"{where}: gold_version이 다르다: 파일 {case.gold_version}, "
                f"VERSION {expected_version}"
            )
        if case.case_id in seen:
            raise EvalError(f"{where}: case_id가 앞 줄과 겹친다")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise NoGold("F2 정답 파일이 0줄이다")
    _바탕_사례_검사(cases)
    return cases


def _바탕_사례_검사(cases: list[RealCase | InjectedCase]) -> None:
    """줄 사이 검사: 주입 사례의 base_case_id는 같은 파일의 real 사례, oa_id도 같아야 한다."""
    reals = {c.case_id: c for c in cases if isinstance(c, RealCase)}
    for n, c in enumerate(cases, start=1):
        if not isinstance(c, InjectedCase) or c.base_case_id is None:
            continue
        base = reals.get(c.base_case_id)
        where = f"정답 사례 {n}번째"  # 빈 줄을 뺀 순번
        if base is None:
            raise EvalError(f"{where}: base_case_id가 같은 파일의 real 사례가 아니다")
        if c.bundle.oa_id is not None and c.bundle.oa_id != base.oa_id:
            raise EvalError(f"{where}: bundle.oa_id가 바탕 사례의 oa_id와 다르다")


def count_cases(cases: list[RealCase | InjectedCase]) -> dict[str, int]:
    """실제 질문 수, 오류 종류별 수, 합계."""
    counts = {"real": 0, **{e: 0 for e in ERROR_KINDS}}
    for c in cases:
        if isinstance(c, RealCase):
            counts["real"] += 1
        else:
            counts[c.error] += 1
    counts["total"] = len(cases)
    return counts


def check_set_size(
    cases: list[RealCase | InjectedCase], min_total: int = 20, min_per_error: int = 1
) -> None:
    """합격 기준 "세트 크기가 기준 이상": 합계와 오류 종류마다 최소 수를 못 넘으면 멈춘다."""
    counts = count_cases(cases)
    if counts["total"] < min_total:
        raise EvalError(f"사례가 {counts['total']}개다 (기준 {min_total}개 이상)")
    for e in ERROR_KINDS:
        if counts[e] < min_per_error:
            raise EvalError(f"오류 종류 {e}가 {counts[e]}개다 (기준 {min_per_error}개 이상)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F2 근거 검토 정답 파일 형식 검사")
    ap.add_argument("--check", required=True, help="evidence_cases.jsonl 경로")
    ap.add_argument("--version", type=int, default=None, help="없으면 data/goldsets/VERSION")
    args = ap.parse_args(argv)
    try:
        version = args.version
        if version is None:
            version = read_goldset_version("data/goldsets")
        cases = load_f2_cases(args.check, version)
        check_set_size(cases)
    except EvalError as e:  # NoGold도 여기로 온다
        print(f"실패: {e}")
        return 1
    c = count_cases(cases)
    kinds = " ".join(f"{e}={c[e]}" for e in ERROR_KINDS)
    print(f"통과: 합계 {c['total']} (real={c['real']} {kinds}), gold_version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
