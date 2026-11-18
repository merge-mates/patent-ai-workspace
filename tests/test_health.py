"""헬스 체크 (이슈 #12 합격 기준: 헬스 체크 테스트가 로컬과 GitHub Actions에서 통과)."""

from fastapi.testclient import TestClient

from patent_ai.api.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())

    res = client.get("/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
