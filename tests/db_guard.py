"""db 테스트가 개발 DB를 건드리지 않게 막는 판별 (순수 함수, DB에 접속하지 않는다)."""

from sqlalchemy.engine import make_url


def 테스트_DB_거부_사유(database_url: str, ci: bool) -> str | None:
    """테스트를 돌려도 되면 None, 안 되면 이유 문장을 돌려준다.

    CI는 일회용 Postgres 서비스라 이름이 patent_ai여도 괜찮다.
    로컬은 DB 이름이 `_test`로 끝나야만 통과한다.
    """
    if ci:
        return None
    이름 = make_url(database_url).database or ""
    if 이름.endswith("_test"):
        return None
    return (
        f"db 테스트가 개발 DB '{이름}'를 건드릴 수 있어 멈춥니다. "
        "`make test-db`로 돌리면 테스트 DB(patent_ai_test)를 씁니다."
    )
