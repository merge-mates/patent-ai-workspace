"""모든 테스트 공통 안전장치: 실수로 진짜 모델 API를 부르거나 과금하지 않게 막는다."""

import os

import pytest

from patent_ai.core.llm import cache as llm_cache
from patent_ai.core.llm import transport as llm_transport
from patent_ai.settings import get_settings
from tests.db_guard import CI_환경인가, 테스트_DB_거부_사유


@pytest.fixture(autouse=True)
def _진짜_모델_호출_막기(monkeypatch):
    # 키 환경 변수를 지워 SDK가 키를 못 찾게 한다
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    # 진짜 전송층을 만드는 순간 예외 (테스트는 가짜·기록된 응답 전송층만 쓴다)
    def blocked(self, *args, **kwargs):
        raise RuntimeError("테스트에서 진짜 전송층을 만들 수 없음 (진짜 호출 막힘)")

    monkeypatch.setattr(llm_transport.AnthropicTransport, "__init__", blocked)
    monkeypatch.setattr(llm_transport.OpenAIEmbedTransport, "__init__", blocked)


@pytest.fixture(autouse=True)
def _전역_상태_격리(monkeypatch, tmp_path):
    # 기본 캐시 폴더를 임시 폴더로 (work/llm_cache를 건드리지 않음)
    monkeypatch.setattr(llm_cache, "DEFAULT_CACHE_DIR", tmp_path / "default_llm_cache")


@pytest.fixture(autouse=True)
def _F4_옛_흐름_고정(monkeypatch):
    # 저장소 기본값(config/f4.yaml)은 11/26부터 사건 단위 보정안 흐름
    # (amendment_enabled false + case_amendment_enabled true)이다.
    # 테스트 대부분은 가짜 응답을 옛 흐름(방향 → 의견서 → 보정안)에 맞춰 두었으니,
    # 설정 폴더를 따로 주지 않고 읽는 곳만 옛 흐름 값으로 바꿔 준다.
    # 새 흐름 테스트는 options를 직접 넘기므로 영향이 없고,
    # 저장소 기본값 자체를 보는 테스트는 config 모듈의 원래 함수를 그대로 쓴다.
    import dataclasses

    from patent_ai.core.f4_response_draft import amendment, config, directions, opinion, run

    original = config.load_f4_options

    def old_flow(config_dir=None):
        options = original(config_dir)
        if config_dir is not None:
            return options
        return dataclasses.replace(options, amendment_enabled=True, case_amendment_enabled=False)

    for module in (amendment, directions, opinion, run):
        monkeypatch.setattr(module, "load_f4_options", old_flow)


@pytest.fixture(autouse=True)
def _개발_DB_보호(request):
    # db 마커 테스트만 검사한다. 로컬에서 DB 이름이 _test로 안 끝나면 실행 전에 멈춘다
    # (CI=1·true일 때만 통과)
    if request.node.get_closest_marker("db") is None:
        return
    사유 = 테스트_DB_거부_사유(get_settings().database_url, ci=CI_환경인가(os.environ.get("CI")))
    if 사유:
        pytest.fail(사유, pytrace=False)
