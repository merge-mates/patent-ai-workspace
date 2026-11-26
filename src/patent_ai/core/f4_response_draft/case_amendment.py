"""사건 단위 보정안 단계 (은진 보정 실험 E 판을 앱 단계로, 이 브랜치).

amendment_enabled false이고 바깥 보정 결과가 없을 때 F4가 부른다. 사건 하나에 한 번,
OA 글자 전체·OA 당시 청구항 전체·출원서 글자를 주고 방향이 다른 보정안 3개를 받아 1번 안을 쓴다.
코드는 확인만 한다: 보정안이 3개인지, 같은 항이 두 번 나오지 않는지, 원래 있는 항이면 amend·delete,
없는 항이면 add인지, 합친 곳(merged_into)이 있는 항을 가리키는지.
1번 안은 바깥 보정 결과로 옮기고(to_external), 코드 검사 표시(check_plan)를 남긴다.
보정이 적법한지는 판단하지 않는다.
"""

import json
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.f4_response_draft.claim_refs import claim_refs
from patent_ai.core.f4_response_draft.inputs import ExternalAmendment, F4Input
from patent_ai.core.f4_response_draft.llm_call import call_with_one_retry
from patent_ai.core.f4_response_draft.plan_check import PlanIssue, check_plan, to_external
from patent_ai.core.llm.limits import RunContext

logger = logging.getLogger(__name__)

STEP = "f4.case_amendment"
SOURCE = "사건 단위 보정안 (AI, 1번 안)"


class PlannedClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    claim: int
    action: Literal["amend", "delete", "add"]
    text: str = ""
    confidence: int = Field(ge=0, le=100)
    reason: str = ""
    merged_into: list[int] = Field(default_factory=list)


class PlanDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    strategy: str
    amended: list[PlannedClaim]


class CaseAmendmentOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    drafts: list[PlanDraft]


class CaseAmendment(BaseModel):
    """사건 단위 보정안 결과: 쓴 1번 안, 바깥 보정 결과, 코드 검사 표시."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str
    external: ExternalAmendment
    checks: list[PlanIssue]
    alternatives: list[str]  # 2·3번 안의 전략 글 (사람이 다른 방향을 볼 수 있게)


def _checked(old: set[int]) -> type[CaseAmendmentOut]:
    class Checked(CaseAmendmentOut):
        @model_validator(mode="after")
        def _보정안_모양(self) -> Checked:
            if len(self.drafts) != 3:
                raise ValueError(f"보정안은 3개여야 함: {len(self.drafts)}개")
            for i, d in enumerate(self.drafts, 1):
                nums = [q.claim for q in d.amended]
                if not nums:
                    raise ValueError(f"보정안 {i}: 바뀌는 청구항이 0개")
                if len(set(nums)) != len(nums):
                    raise ValueError(f"보정안 {i}: 같은 청구항이 두 번")
                for q in d.amended:
                    if (q.action == "add") == (q.claim in old):
                        raise ValueError(
                            f"보정안 {i} {q.claim}항: 원래 있는 항은 amend·delete, 없는 항은 add"
                        )
                    if q.action != "delete" and not q.text.strip():
                        raise ValueError(f"보정안 {i} {q.claim}항 글이 비어 있음")
                    if q.action != "delete" and q.merged_into:
                        raise ValueError(
                            f"보정안 {i} {q.claim}항: delete가 아니면 merged_into는 빈 목록"
                        )
                    if set(q.merged_into) - old - set(nums):
                        raise ValueError(f"보정안 {i} {q.claim}항: merged_into에 없는 항")
            return self

    return Checked


def _variables(inp: F4Input, limit_note: str) -> dict[str, str]:
    old = {c.claim: c.text for c in inp.claims_text}
    refs = claim_refs(inp.claims_text)
    targets: dict[int, list[dict]] = {}
    for r in inp.oa.rejections:
        for n in r.claims.value or []:
            targets.setdefault(n, []).append(
                {"no": r.no, "kind": r.kind.value, "article": r.article.value or r.article.raw_text}
            )
    rows = [
        {
            "claim": n,
            "independent": n in refs and refs[n].depends_on == [],
            "rejections": targets[n],
        }
        for n in sorted(targets)
    ]
    free = [n for n in sorted(old) if n not in targets]
    pages = inp.oa_pages.pages if inp.oa_pages else []
    spec = inp.spec.pages if inp.spec else []
    if not pages:
        logger.warning("f4.case_amendment %s: OA 쪽 글자가 없어 F1 정리만 줌", inp.oa.oa_id)
    oa_text = "\n".join(p.text for p in pages) or json.dumps(
        [r.model_dump(mode="json") for r in inp.oa.rejections], ensure_ascii=False
    )
    return {
        "targets": json.dumps(rows, ensure_ascii=False),
        "free": ", ".join(map(str, free)) or "없음",
        "oa": oa_text,
        "claims": "\n\n".join(f"【청구항 {n}】\n{t}" for n, t in sorted(old.items())),
        "application": "\n".join(p.text for p in spec) or "(출원서 글자 없음)",
        "limit_note": f"\n{limit_note}\n" if limit_note else "",
    }


def build_case_amendment(inp: F4Input, ctx: RunContext, limit_note: str = "") -> CaseAmendment:
    """사건 하나의 보정안. 모델 호출 실패·출력 검사 두 번 실패는 예외로 올린다."""
    old = {c.claim: c.text for c in inp.claims_text}
    if not old:
        raise ValueError(f"OA 당시 청구항 글자가 없어 보정안을 만들 수 없음: {inp.oa.oa_id}")
    out = call_with_one_retry(STEP, _variables(inp, limit_note), _checked(set(old)), ctx)
    first = out.drafts[0]
    plan = [q.model_dump() for q in first.amended]
    spec = "\n".join(p.text for p in inp.spec.pages) if inp.spec else ""
    return CaseAmendment(
        strategy=first.strategy,
        external=to_external(old, plan, source=SOURCE),
        checks=check_plan(old, plan, spec),
        alternatives=[d.strategy for d in out.drafts[1:]],
    )
