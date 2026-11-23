"""법률 질문 대화 저장소의 값 타입·약속(Protocol)·메모리 구현 (이슈 #29 task-2).

대화 하나 = 사건 없이도 여러 번 묻고 답하는 줄. 턴마다 질문, 시점·자료 유형이 앞 질문과
달라졌는지(scope_changed), 답(LegalEvidenceBundle)을 쌓는다. DB 구현은 chat_store_pg.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.legal_evidence import LegalEvidenceBundle, LegalQuestion


class ChatNotFound(KeyError):
    """없는 대화에 턴을 더하려 할 때."""


class ChatCorrupt(Exception):
    """저장된 턴을 스키마대로 못 읽을 때. 빈 대화로 넘기지 않고 오류로 알린다."""


@dataclass(frozen=True)
class LegalChatTurn:
    no: int  # 1부터
    question: LegalQuestion
    scope_changed: bool
    bundle: LegalEvidenceBundle
    created_at: datetime


@dataclass(frozen=True)
class LegalChat:
    chat_id: str
    case_id: str | None
    created_at: datetime
    turns: list[LegalChatTurn] = field(default_factory=list)  # no 순서

    @property
    def last_question(self) -> LegalQuestion | None:
        """앞 질문. 다음 질문이 시점·자료 유형을 물려받을 때 쓴다."""
        return self.turns[-1].question if self.turns else None

    @property
    def prior_evidence(self) -> list[str]:
        """앞 턴들에서 확인된(confirmed) 근거의 색인 조각 ID. 순서 유지, 중복 제거.

        이어 묻는 질문의 기준일에서 이 조각들이 아직 맞는 판인지 다시 보는 데 쓴다.
        """
        seen: dict[str, None] = {}
        for turn in self.turns:
            for claim in turn.bundle.claims:
                for src in claim.sources:
                    chunk_id = src.evidence.chunk_id
                    if chunk_id and src.status.value == StatusValue.CONFIRMED:
                        seen.setdefault(chunk_id, None)
        return list(seen)


def new_chat_id() -> str:
    return "lc_" + uuid.uuid4().hex


class LegalChatStore(Protocol):
    def create(self, case_id: str | None, now: datetime) -> LegalChat: ...

    def get(self, chat_id: str) -> LegalChat | None: ...

    def add_turn(
        self,
        chat_id: str,
        question: LegalQuestion,
        scope_changed: bool,
        bundle: LegalEvidenceBundle,
        now: datetime,
    ) -> LegalChatTurn: ...


class InMemoryLegalChatStore:
    """테스트·DB 없는 실행용."""

    def __init__(self) -> None:
        self._chats: dict[str, LegalChat] = {}

    def create(self, case_id: str | None, now: datetime) -> LegalChat:
        chat = LegalChat(chat_id=new_chat_id(), case_id=case_id, created_at=now)
        self._chats[chat.chat_id] = chat
        return chat

    def get(self, chat_id: str) -> LegalChat | None:
        chat = self._chats.get(chat_id)
        return replace(chat, turns=list(chat.turns)) if chat else None  # 복사본을 준다

    def add_turn(
        self,
        chat_id: str,
        question: LegalQuestion,
        scope_changed: bool,
        bundle: LegalEvidenceBundle,
        now: datetime,
    ) -> LegalChatTurn:
        chat = self._chats.get(chat_id)
        if chat is None:
            raise ChatNotFound(chat_id)
        turn = LegalChatTurn(len(chat.turns) + 1, question, scope_changed, bundle, now)
        chat.turns.append(turn)
        return turn
