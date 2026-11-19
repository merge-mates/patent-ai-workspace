"""표의 기본 키(ID) 만들기. 종류 앞글자 + 무작위 글자 (예: `c_3f9a…`, `oa_…`).

결과 스키마·API가 ID를 글자(str)로 쓰고, 두 사람 DB끼리 번호가 겹치지 않게 uuid4를 쓴다.
"""

from uuid import uuid4


def new_id(prefix: str) -> str:
    """`<prefix>_<uuid4 32글자>`."""
    return f"{prefix}_{uuid4().hex}"


def id_factory(prefix: str):
    """SQLAlchemy `default=`에 넣을, 인자 없는 함수."""
    return lambda: new_id(prefix)
