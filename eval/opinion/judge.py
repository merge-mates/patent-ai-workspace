"""의견서 LLM 저지 (11/26 골 모드 P2). 모델 호출은 patent_ai.core.llm.call_model만 거친다.

- 주 점수(opinion_main): 반박 논점마다 0·1·2 (실제 의견서를 정답으로 받음)
- 보조 점수(opinion_aux): 기준 c1·c2·c3·c5 (실제 의견서 없이)
설정 config/eval_judge.yaml, 프롬프트 prompts/eval/ (system은 .system.md).
답 모양이 틀리면(논점 id가 빠지거나 남음 포함) 검사 오류를 붙여 attempt 2로 한 번 더 부른다.
모르는 칸(모델이 더 붙인 설명 칸)은 버리고 읽는다 (점수 칸만 검사).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext

MAIN_STEP = "eval_judge.opinion_main"
AUX_STEP = "eval_judge.opinion_aux"
Score = Literal[0, 1, 2]


class MainIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    filed_point: str | None = None
    draft_point: str | None = None
    score: Score
    reason: str
    evidence_check: Literal["맞음", "일부", "어긋남", "없음", "확인 불가"]


class MainOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issues: list[MainIssue]


def main_schema(ids: list[str]) -> type[MainOut]:
    """논점 id가 준 목록과 똑같아야 통과하는 출력 검사 스키마 (빠짐·덧붙임·겹침은 다시 부름)."""
    want = sorted(ids)

    class CheckedMainOut(MainOut):
        @model_validator(mode="after")
        def _논점_id가_같다(self) -> CheckedMainOut:
            got = sorted(i.id for i in self.issues)
            if got != want:
                raise ValueError(f"논점 id가 다름: 받은 {len(got)}개, 준 {len(want)}개")
            return self

    return CheckedMainOut


class Crit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: Score
    reason: str


class C1(Crit):
    missing: list[str] = Field(default_factory=list)


class JudgeError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["major", "minor"]
    what: str


class C3(Crit):
    major: int = Field(ge=0)
    minor: int = Field(ge=0)
    unverifiable: int = Field(ge=0, default=0)
    errors: list[JudgeError] = Field(default_factory=list)


class C5(Crit):
    explained: int = Field(ge=0)
    changed: int = Field(ge=0)


class AuxOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    c1: C1
    c2: Crit
    c3: C3
    c5: C5


RETRY_NOTE = (
    "\n앞 답이 출력 형식 검사에 떨어졌습니다. 같은 형식으로 다시 답하세요. 검사 오류:\n{error}\n"
)


def _call(step: str, variables: dict, schema, ctx: RunContext):
    """한 번 부르고, 답 모양이 틀리면 검사 오류를 붙여 attempt 2로 한 번 더 (그래도 틀리면 예외)."""
    try:
        return call_model(step, {**variables, "retry_note": ""}, schema, ctx=ctx, attempt=1)
    except ModelOutputInvalid as e:
        note = RETRY_NOTE.format(error=str(e)[:1000])
    return call_model(step, {**variables, "retry_note": note}, schema, ctx=ctx, attempt=2)


def judge_main(variables: dict, issue_ids: list[str], ctx: RunContext):
    """variables: issues·oa_text·claims_at_oa·amendment·comparison·filed·draft (모두 글자)."""
    if not issue_ids:
        raise ValueError("반박 논점이 0개인 사건은 주 점수 저지를 부르지 않는다")
    return _call(MAIN_STEP, variables, main_schema(issue_ids), ctx)


def judge_aux(variables: dict, ctx: RunContext):
    """variables: issues·oa_text·claims_at_oa·amendment·comparison·draft (실제 의견서 없음)."""
    return _call(AUX_STEP, variables, AuxOut, ctx)
