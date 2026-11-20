"""db 테스트가 개발 DB를 건드리지 않게 막는 판별 함수와 conftest 가드 (DB 없이 돈다)."""

from pathlib import Path

import pytest

from tests.db_guard import CI_환경인가, 테스트_DB_거부_사유, 테스트_DB_주소

pytest_plugins = ["pytester"]

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


@pytest.mark.parametrize("값", ["1", "true", "TRUE", "True"])
def test_CI가_1이나_true면_CI로_본다(값):
    assert CI_환경인가(값) is True


@pytest.mark.parametrize("값", [None, "", "0", "false", "False", "no"])
def test_CI가_비었거나_false·0이면_CI로_보지_않는다(값):
    assert CI_환경인가(값) is False


def test_테스트_DB_주소는_계정·포트를_따르고_이름만_바꾼다():
    주소 = 테스트_DB_주소("postgresql+psycopg://me:secret@localhost:5433/patent_ai")
    assert 주소 == "postgresql+psycopg://me:secret@localhost:5433/patent_ai_test"


# 아래는 conftest의 autouse 가드가 db 마커 테스트에 실제로 걸리는지 본다.
# 저장소 conftest를 임시 폴더에 그대로 복사하고, 별도 pytest 프로세스로 돌린다 (DB 접속 없음).
저장소_뿌리 = Path(__file__).resolve().parent.parent
_마커_테스트 = """
import pytest

@pytest.mark.db
def test_db_마커():
    pass

def test_마커_없음():
    pass
"""


def _가드_돌리기(pytester, monkeypatch, database_url, ci):
    pytester.makeconftest((저장소_뿌리 / "tests" / "conftest.py").read_text(encoding="utf-8"))
    pytester.makeini("[pytest]\nmarkers =\n    db: 실제 Postgres가 필요한 테스트\n")
    pytester.makepyfile(test_marker=_마커_테스트)
    monkeypatch.setenv("PYTHONPATH", str(저장소_뿌리))
    monkeypatch.setenv("DATABASE_URL", database_url)
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)
    return pytester.runpytest_subprocess()


@pytest.mark.parametrize("ci", [None, "false", "0"])
def test_로컬에서_개발_DB면_db_마커_테스트만_시작_전에_멈춘다(pytester, monkeypatch, ci):
    결과 = _가드_돌리기(pytester, monkeypatch, 개발_주소, ci)
    결과.assert_outcomes(passed=1, errors=1)  # 가드는 fixture라 오류로 잡힌다
    결과.stdout.fnmatch_lines(["*개발 DB 'patent_ai'*"])


def test_로컬에서_테스트_DB면_db_마커_테스트가_돈다(pytester, monkeypatch):
    결과 = _가드_돌리기(pytester, monkeypatch, 테스트_주소, None)
    결과.assert_outcomes(passed=2)


def test_CI가_true면_개발_DB_이름이어도_돈다(pytester, monkeypatch):
    결과 = _가드_돌리기(pytester, monkeypatch, 개발_주소, "true")
    결과.assert_outcomes(passed=2)
