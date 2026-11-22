"""법률 질문 대화 엔드포인트 (이슈 #29). 판단은 core/f2_legal_research/chat.py에 있다.

만들기 `POST /legal-chats`, 묻기 `POST /legal-chats/{id}/messages`, 보기 `GET /legal-chats/{id}`.
답은 법률 근거 묶음(LegalEvidenceBundle)을 `result`에 그대로 담는다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, ValidationError

from patent_ai.api.deps import (
    LegalChatUnit,
    LegalIndex,
    get_f2_settings,
    get_legal_chat_unit,
    get_legal_index,
    get_today,
)
from patent_ai.api.errors import AppError
from patent_ai.core.f2_legal_research.chat import (
    ChatAsk,
    answer_question,
    missing_index_answer,
    next_question,
)
from patent_ai.core.f2_legal_research.chat_store import ChatCorrupt, LegalChat
from patent_ai.core.f2_legal_research.run import F2Settings
from patent_ai.core.schemas.legal_evidence import LegalEvidenceBundle, LegalQuestion

router = APIRouter()


def _inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """모델 스키마의 `$defs` 참조를 그 자리에 풀어 넣는다 (OpenAPI에 `#/$defs/..`가 깨지지 않게)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return walk(defs[ref.removeprefix("#/$defs/")])
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class CreateChatIn(BaseModel):
    case_id: str | None = None


class CreatedChatOut(BaseModel):
    chat_id: str


class AnswerOut(BaseModel):
    chat_id: str
    no: int
    scope_changed: bool  # 앞 질문과 시점 또는 자료 유형이 달라졌는가
    result: LegalEvidenceBundle


class TurnOut(BaseModel):
    no: int
    question: LegalQuestion
    scope_changed: bool
    created_at: datetime
    result: LegalEvidenceBundle


class ChatOut(BaseModel):
    chat_id: str
    case_id: str | None
    created_at: datetime
    turns: list[TurnOut]
    prior_evidence: list[str]  # 앞 턴에서 확인된 색인 조각 ID


Unit = Annotated[LegalChatUnit, Depends(get_legal_chat_unit)]
Index = Annotated[LegalIndex | None, Depends(get_legal_index)]
Settings = Annotated[F2Settings, Depends(get_f2_settings)]
Today = Annotated[date, Depends(get_today)]


def _read(unit: LegalChatUnit, chat_id: str) -> LegalChat:
    """대화 읽기. 없으면 404, 저장본을 못 읽으면 조용히 비우지 않고 오류."""
    try:
        chat = unit.store.get(chat_id)
    except ChatCorrupt as e:
        raise AppError(
            500, "chat_corrupt", "확인되지 않음: 저장된 대화를 읽지 못함 (새 대화로 다시 질문 필요)"
        ) from e
    if chat is None:
        raise AppError(404, "chat_not_found", "대화를 찾을 수 없습니다")
    return chat


@router.post("/legal-chats", status_code=201, response_model=CreatedChatOut)
def create_chat(body: CreateChatIn, unit: Unit) -> CreatedChatOut:
    try:
        chat = unit.store.create(body.case_id, datetime.now(UTC))
        unit.commit()
    except Exception:
        unit.rollback()
        raise
    return CreatedChatOut(chat_id=chat.chat_id)


@router.post(
    "/legal-chats/{chat_id}/messages",
    response_model=AnswerOut,
    # 검사는 아래에서 직접 하므로 요청 스키마는 OpenAPI에 따로 싣는다
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _inline_schema(ChatAsk)}},
        }
    },
)
def ask(
    chat_id: str,
    unit: Unit,
    index: Index,
    settings: Settings,
    today: Today,
    # 빈 글·잘못된 값은 validation_error 대신 invalid_question으로 알린다
    body: Annotated[Any, Body()],
) -> AnswerOut:
    if not isinstance(body, dict):
        raise AppError(422, "invalid_question", "본문은 JSON 객체여야 합니다")
    try:
        ask_in = ChatAsk.model_validate(body)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise AppError(422, "invalid_question", f"{where}: {first['msg']}".strip(": ")) from e
    chat = _read(unit, chat_id)
    question, scope_changed = next_question(chat.last_question, ask_in)
    bundle_id = f"{chat_id}:{len(chat.turns) + 1}"
    if index is None:
        bundle = missing_index_answer(
            question,
            bundle_id=bundle_id,
            index_version=settings.index_version,
            checked_on=today,
        )
    else:
        bundle = answer_question(
            question,
            bundle_id=bundle_id,
            pool=index.pool,
            searcher=index.searcher,
            checked_on=today,
            prior_evidence=chat.prior_evidence,
            search_k=settings.chat_search_k,
        )
    try:
        turn = unit.store.add_turn(chat_id, question, scope_changed, bundle, datetime.now(UTC))
        unit.commit()
    except Exception:
        unit.rollback()
        raise
    return AnswerOut(chat_id=chat_id, no=turn.no, scope_changed=scope_changed, result=bundle)


@router.get("/legal-chats/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: str, unit: Unit) -> ChatOut:
    chat = _read(unit, chat_id)
    return ChatOut(
        chat_id=chat.chat_id,
        case_id=chat.case_id,
        created_at=chat.created_at,
        turns=[
            TurnOut(
                no=t.no,
                question=t.question,
                scope_changed=t.scope_changed,
                created_at=t.created_at,
                result=t.bundle,
            )
            for t in chat.turns
        ],
        prior_evidence=chat.prior_evidence,
    )
