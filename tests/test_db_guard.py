"""db 테스트가 개발 DB를 건드리지 않게 막는 판별 함수 (DB 없이 도는 단위 테스트)."""

from tests.db_guard import 테스트_DB_거부_사유

개발_주소 = "postgresql+psycopg://patent:patent@localhost:5432/patent_ai"
테스트_주소 = "postgresql+psycopg://patent:patent@localhost:5432/patent_ai_test"


def test_개발_DB_이름이면_거부한다():
    assert 테스트_DB_거부_사유(개발_주소, ci=False) is not None


def test_테스트_DB_이름이면_통과한다():
    assert 테스트_DB_거부_사유(테스트_주소, ci=False) is None


def test_CI에서는_개발_DB_이름이어도_통과한다():
    assert 테스트_DB_거부_사유(개발_주소, ci=True) is None


def test_거부_메시지에_DB_이름과_해결법이_들어간다():
    사유 = 테스트_DB_거부_사유(개발_주소, ci=False)
    assert "patent_ai" in 사유
    assert "make test-db" in 사유
