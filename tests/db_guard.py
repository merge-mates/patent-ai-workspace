"""db 테스트가 개발 DB를 건드리지 않게 막는 판별 (순수 함수, DB에 접속하지 않는다)."""

from sqlalchemy.engine import make_url

TEST_DB_NAME = "patent_ai_test"


def CI_환경인가(값: str | None) -> bool:
    """환경 변수 CI가 "1"·"true"(대소문자 무시)일 때만 CI로 본다.

    GitHub Actions는 CI=true를 넣는다. CI=false·CI=0으로는 로컬에서 가드를 지나가지 못한다.
    """
    return (값 or "").strip().lower() in {"1", "true"}


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
        f"`make test-db`로 돌리면 테스트 DB({TEST_DB_NAME})를 씁니다."
    )


def 테스트_DB_주소(database_url: str) -> str:
    """개발 DB 주소에서 DB 이름만 테스트 DB로 바꾼다 (계정·비밀번호·포트는 그대로 따른다)."""
    return make_url(database_url).set(database=TEST_DB_NAME).render_as_string(hide_password=False)


if __name__ == "__main__":
    # make test-db가 부른다: .env의 DATABASE_URL(없으면 기본값)을 따라 테스트 DB 주소를 찍는다.
    # 비밀번호가 들어 있으니 Makefile은 이 출력을 화면에 보이지 않게 쓴다.
    from patent_ai.settings import get_settings

    print(테스트_DB_주소(get_settings().database_url))
