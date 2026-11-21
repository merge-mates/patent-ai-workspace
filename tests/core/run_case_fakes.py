"""#180 한 바퀴(F1 → F3 → F2 넘김 → F4)를 서버 쪽 테스트에서 다시 쓰는 도움 함수.

모델 답은 가짜 응답(FakeTransport), F1 두 단계와 F3 검색 자원은 지어낸 것으로 바꾼다.
네트워크·키·DB 없음. 앱 코드에서 import하지 않는다.
"""

from patent_ai.core.f1_oa_reader.pages import PdfReadError
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult
from tests.core.agents.test_fixed_order_f3_f4 import (
    CASE,
    CHECKED_ON,
    F1,
    TERM,
    _go,
    _real_config,
    _responses,
    _texts,
)
from tests.core.f3 import scenario
from tests.core.f3.fakes import claim_row

__all__ = [
    "CHECKED_ON",
    "fake_ctx",
    "real_config",
    "real_outcome",
    "texts",
    "wire",
    "wire_broken_pdf",
]

texts = _texts
real_config = _real_config


def wire(monkeypatch) -> OAResult:
    """F1 두 단계(extract_pages·read_oa)와 F3 검색 자원을 지어낸 것으로 바꾼다."""
    pages = PageText.model_validate_json((F1 / "notice_basic.pages.json").read_text("utf-8"))
    oa = OAResult.model_validate(
        {**CASE["oa"], "claim_rows": [claim_row(2, 2, clarity_terms=[TERM]).model_dump()]}
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", lambda *a, **k: oa)
    monkeypatch.setattr(
        f3_run, "make_search_resources", lambda config, ctx: (scenario.searcher(), scenario.REPO)
    )
    return oa


def wire_broken_pdf(monkeypatch, secret: str) -> None:
    """PDF 읽기가 원문이 섞인 예외 글로 실패하게 한다 (실패 이유에 원문이 새지 않는지 볼 때)."""

    def broken(path, document_id):
        raise PdfReadError(f"쪽 글자: {secret}")

    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", broken)


def fake_ctx(run_id: str) -> RunContext:
    """가짜 응답만 쓰는 실행 맥락 (실행마다 새로)."""
    return RunContext(
        run_id=run_id,
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=FakeTransport(_responses()),
    )


def real_outcome(tmp_path, monkeypatch):
    """한 바퀴를 돌린 RunOutcome (results에 진짜 OAResult·F3Result·F4Output)."""
    wire(monkeypatch)
    out, _ = _go(tmp_path)
    assert out.state == "succeeded", out.error
    return out
