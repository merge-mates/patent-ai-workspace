"""모든 테스트 공통 안전장치: 실수로 진짜 모델 API를 부르거나 과금하지 않게 막는다."""

import os

import pytest

from patent_ai.core.llm import cache as llm_cache
from patent_ai.core.llm import transport as llm_transport
from patent_ai.settings import get_settings
from tests.db_guard import 테스트_DB_거부_사유


@pytest.fixture(autouse=True)
def _진짜_모델_호출_막기(monkeypatch):
    # 키 환경 변수를 지워 SDK가 키를 못 찾게 한다
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # 진짜 전송층을 만드는 순간 예외 (테스트는 가짜·녹화 전송층만 쓴다)
    def blocked(self, *args, **kwargs):
        raise RuntimeError("테스트에서 진짜 전송층을 만들 수 없음 (진짜 호출 막힘)")

    monkeypatch.setattr(llm_transport.AnthropicTransport, "__init__", blocked)
    monkeypatch.setattr(llm_transport.OpenAIEmbedTransport, "__init__", blocked)


@pytest.fixture(autouse=True)
def _전역_상태_격리(monkeypatch, tmp_path):
    # 기본 캐시 폴더를 임시 폴더로 (work/llm_cache를 건드리지 않음)
    monkeypatch.setattr(llm_cache, "DEFAULT_CACHE_DIR", tmp_path / "default_llm_cache")


@pytest.fixture(autouse=True)
def _개발_DB_보호(request):
    # db 마커 테스트만 검사한다. 로컬에서 DB 이름이 _test로 안 끝나면 실행 전에 멈춘다 (CI는 통과)
    if request.node.get_closest_marker("db") is None:
        return
    사유 = 테스트_DB_거부_사유(get_settings().database_url, ci=bool(os.environ.get("CI")))
    if 사유:
        pytest.fail(사유, pytrace=False)
