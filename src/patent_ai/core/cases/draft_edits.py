"""사람이 초안을 고치는 판단 (이슈 #304 T1). 라우터(api/drafts.py)는 이 함수만 부른다.

PATCH /drafts/{draft_id}: 의견서 칸 하나(section) 또는 보정 청구항 하나(claim)의 글을 고친다.
- AI 원문(ai_text)은 건드리지 않고, 사람이 쓴 글만 human_text에 둔다 (origin human_edited).
  AI 원문과 같은 글을 보내면 고친 것을 되돌린다 (human_text 없음, origin ai_generated).
- 고칠 초안은 지금 화면에 보이는 초안이다: OA 정리와 같은 실행(보여 줄 실행)의 F4 결과.
  그 실행의 F4 결과 줄 안 drafts만 바꿔 저장하므로 다시 열면(GET drafts) 고친 글이 나온다.
- 그 OA에 진행 중 실행이 있으면 받지 않는다 (RunInProgressError → 409). 그 실행이 끝나면 새 초안이
  보이게 되어, 옛 실행 줄에 저장한 고침이 화면에서 사라지기 때문이다 (방향 고르기와 같은 규칙).
- 중간 결과(F1·F2·F3)와 방향 후보는 고치지 않는다.
"""

from __future__ import annotations

from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.start_run import RunInProgressError, has_active_run
from patent_ai.core.cases.step_results import StepBody, StepResultStore
from patent_ai.core.cases.store import CaseAppStore
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.drafts import AmendedClaim, Drafts, OpinionKey, OpinionSection

_PREFIX = "dr:"  # draft_id = dr:<oa_id> (f4_response_draft/opinion.py)


class DraftNotFoundError(LookupError):
    """그 draft_id인 초안이 지금 보이는 실행에 없다 (API는 404 draft_not_found)."""


class InvalidDraftEditError(ValueError):
    """칸과 청구항 중 정확히 하나가 아니거나, 없는 칸이거나, 글이 비었다 (API는 422)."""


class ClaimNotEditableError(ValueError):
    """그 번호의 보정 청구항이 없거나 보류(AI 원문 없음)라 고칠 수 없다 (API는 422)."""


def _edited(ai_text: str, text: str) -> tuple[str | None, Origin]:
    """보낸 글을 (human_text, origin)으로. AI 원문과 같으면 고친 것이 아니다."""
    if text == ai_text:
        return None, Origin.AI_GENERATED
    return text, Origin.HUMAN_EDITED


def apply_edit(drafts: Drafts, *, section: str | None, claim: int | None, text: str) -> Drafts:
    """초안 한 칸을 고친 새 초안. 맨 위 origin은 고친 칸이 남았는지로 다시 정한다."""
    if (section is None) == (claim is None):
        raise InvalidDraftEditError("section과 claim 중 하나만 보내야 함")
    if not text.strip():
        raise InvalidDraftEditError("고친 글이 비어 있음")
    opinion, claims = list(drafts.opinion), list(drafts.claims)
    if section is not None:
        try:
            key = OpinionKey(section)
        except ValueError:
            raise InvalidDraftEditError(f"없는 의견서 칸: {section}") from None
        i = next((n for n, s in enumerate(opinion) if s.key == key), None)
        if i is None:
            raise InvalidDraftEditError(f"이 초안에 없는 의견서 칸: {section}")
        human, origin = _edited(opinion[i].ai_text, text)
        data = opinion[i].model_dump() | {"human_text": human, "origin": origin}
        opinion[i] = OpinionSection.model_validate(data)
    else:
        i = next((n for n, c in enumerate(claims) if c.claim == claim), None)
        # 보류한 청구항은 고칠 AI 원문이 없다 (방향을 고르면 초안이 생긴다)
        if i is None or claims[i].ai_text is None:
            raise ClaimNotEditableError(f"고칠 수 있는 보정 초안이 없음: 청구항 {claim}")
        human, origin = _edited(claims[i].ai_text, text)
        claims[i] = AmendedClaim.model_validate(
            claims[i].model_dump() | {"human_text": human, "origin": origin}
        )
    edited = any(s.origin == Origin.HUMAN_EDITED for s in opinion) or any(
        c.origin == Origin.HUMAN_EDITED for c in claims
    )
    top = Origin.HUMAN_EDITED if edited else Origin.AI_GENERATED
    # 다시 검사를 거쳐 만든다 (frozen 모델이라 칸만 바꿔 검사를 우회하지 않게)
    return Drafts.model_validate(
        drafts.model_dump() | {"opinion": opinion, "claims": claims, "origin": top}
    )


def edit_draft(
    draft_id: str,
    *,
    section: str | None,
    claim: int | None,
    text: str,
    store: CaseAppStore,
    oa_results: OAResultStore,
    step_results: StepResultStore,
) -> Drafts:
    """지금 보이는 초안 한 칸을 고쳐 저장하고 고친 초안 전체를 돌려준다."""
    if not draft_id.startswith(_PREFIX):
        raise DraftNotFoundError(draft_id)
    oa_id = draft_id.removeprefix(_PREFIX)
    oa = store.get_oa(oa_id)
    if oa is None:
        raise DraftNotFoundError(draft_id)
    # 도는 실행이 끝나면 다른 초안이 보이게 되어 지금 고친 글이 사라진다: 끝난 뒤 고친다
    if has_active_run(oa.latest_run.state if oa.latest_run else None):
        raise RunInProgressError(oa_id)
    saved = oa_results.latest_visible_oa_result(oa_id)
    if saved is None:
        raise DraftNotFoundError(draft_id)
    out: list[Drafts] = []

    def change(body: StepBody) -> StepBody:
        if not isinstance(body, F4Output) or body.drafts is None:
            raise DraftNotFoundError(draft_id)
        if body.drafts.draft_id != draft_id:
            raise DraftNotFoundError(draft_id)
        new = apply_edit(body.drafts, section=section, claim=claim, text=text)
        out.append(new)
        return body.model_copy(update={"drafts": new})

    if step_results.update_step_result(saved.run_id, "f4", change) is None:
        raise DraftNotFoundError(draft_id)  # 그 실행은 F4를 넘겼다
    return out[0]
