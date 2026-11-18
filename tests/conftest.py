"""모든 테스트 공통 안전장치: 실수로 진짜 모델 API를 부르거나 과금하지 않게 막는다."""

import pytest

from patent_ai.core.llm import transport as llm_transport


@pytest.fixture(autouse=True)
def _진짜_모델_호출_막기(monkeypatch):
    # 키 환경 변수를 지워 SDK가 키를 못 찾게 한다
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # 진짜 전송층을 만드는 순간 예외 (테스트는 가짜·녹화 전송층만 쓴다)
    def blocked(self, *args, **kwargs):
        raise RuntimeError("테스트에서 AnthropicTransport를 만들 수 없음 (진짜 호출 막힘)")

    monkeypatch.setattr(llm_transport.AnthropicTransport, "__init__", blocked)
