"""지휘(run_case)의 사건 채우기 단계 구현 (이슈 #54): 사건 채우기 + 채운 사건에서 F3·F4 글자.

이미 채운 사건(다시 실행)이어도 글자는 다시 만든다 (texts_source가 DB 판에서 만든다).
"""

from __future__ import annotations

from patent_ai.core.agents.orchestrator import FilledTexts
from patent_ai.core.cases.case_source.fill import FillOutcome, PostgresCaseSourceFill
from patent_ai.core.cases.run_inputs import TextsSource

# 못 가져온 자료 이름 (단계 기록에 보이는 글)
_WHAT = {
    "admin_history": "행정 이력",
    "claim_history": "청구항 이력",
    "application_document": "출원서",
}


def describe_fill(source: str, out: FillOutcome, has_texts: bool) -> str:
    """단계 기록 한 줄: 채웠는지·건너뛴 이유, 못 가져온 것, 글자를 만들었는지."""
    parts = [f"{source}로 채움" if out.filled else f"채우지 않음: {out.why}"]
    for m in out.missing:
        parts.append(f"{_WHAT[m.what]} 없음 ({m.reason.value}: {m.detail})")
    if not has_texts:
        parts.append("OA 당시 청구항·명세서 글자를 못 만듦 (판 문서 없음 등, 서버 로그)")
    return " / ".join(parts)


class SourceCaseFiller:
    """orchestrator.CaseFiller 구현."""

    def __init__(self, fill: PostgresCaseSourceFill, texts: TextsSource, source_name: str) -> None:
        self._fill = fill
        self._texts = texts
        self._source = source_name

    def fill(self, oa_id: str, application_number: str, dispatch_number: str) -> FilledTexts:
        out = self._fill.fill_before_f3(oa_id, application_number, dispatch_number)
        texts = self._texts.texts_for(oa_id)
        return FilledTexts(
            texts=texts, reason=describe_fill(self._source, out, has_texts=texts is not None)
        )
