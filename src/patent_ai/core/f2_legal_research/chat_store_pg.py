"""법률 질문 대화 저장소의 Postgres 구현 (이슈 #29 task-2). 표는 db/models/legal_chats.py.

세션을 받아 flush까지만 한다. 커밋·롤백은 부르는 쪽이 한다 (요청 하나의 세션 안에서 쓴다).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from patent_ai.core.f2_legal_research.chat_store import (
    ChatCorrupt,
    ChatNotFound,
    LegalChat,
    LegalChatTurn,
    new_chat_id,
)
from patent_ai.core.schemas.legal_evidence import LegalEvidenceBundle, LegalQuestion
from patent_ai.db.models import LegalChatRow, LegalChatTurnRow


class PostgresLegalChatStore:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, case_id: str | None, now: datetime) -> LegalChat:
        row = LegalChatRow(chat_id=new_chat_id(), case_id=case_id, created_at=now)
        self._s.add(row)
        self._s.flush()  # 없는 사건이면 여기서 FK 오류
        return LegalChat(row.chat_id, row.case_id, row.created_at)

    def get(self, chat_id: str) -> LegalChat | None:
        row = self._s.get(LegalChatRow, chat_id)
        if row is None:
            return None
        q = (
            select(LegalChatTurnRow)
            .where(LegalChatTurnRow.chat_id == chat_id)
            .order_by(LegalChatTurnRow.no)
        )
        turns = [_to_turn(chat_id, r) for r in self._s.scalars(q)]
        return LegalChat(row.chat_id, row.case_id, row.created_at, turns)

    def add_turn(
        self,
        chat_id: str,
        question: LegalQuestion,
        scope_changed: bool,
        bundle: LegalEvidenceBundle,
        now: datetime,
    ) -> LegalChatTurn:
        if self._s.get(LegalChatRow, chat_id) is None:
            raise ChatNotFound(chat_id)
        last = self._s.scalar(
            select(func.max(LegalChatTurnRow.no)).where(LegalChatTurnRow.chat_id == chat_id)
        )
        # 번호는 마지막 + 1 (같은 대화에 동시에 더하면 PK가 막는다)
        row = LegalChatTurnRow(
            chat_id=chat_id,
            no=(last or 0) + 1,
            question=question.model_dump(mode="json"),
            scope_changed=scope_changed,
            bundle=bundle.model_dump(mode="json"),
            created_at=now,
        )
        self._s.add(row)
        self._s.flush()
        return LegalChatTurn(row.no, question, scope_changed, bundle, row.created_at)


def _to_turn(chat_id: str, row: LegalChatTurnRow) -> LegalChatTurn:
    # 저장된 jsonb를 스키마로 다시 검사한다. 못 읽으면 조용히 넘기지 않고 오류
    try:
        return LegalChatTurn(
            no=row.no,
            question=LegalQuestion.model_validate(row.question),
            scope_changed=row.scope_changed,
            bundle=LegalEvidenceBundle.model_validate(row.bundle),
            created_at=row.created_at,
        )
    except ValidationError as e:
        raise ChatCorrupt(f"{chat_id} 턴 {row.no}을 읽지 못함") from e
