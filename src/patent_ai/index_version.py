"""색인 판 이름 `<말뭉치>-idx-v<N>` 규칙 하나 (예: law-idx-v2, cite-idx-v2).

넣기(retrieval/law_index_db), 메모리 저장소(retrieval/repository), 법령 색인(retrieval/law_index),
벡터 채우기(core/index_embed), 덤프(db/index_dump)가 같이 쓴다.
db/도 쓰므로 retrieval·core를 import하지 않는다 (ADR 0003 부르는 방향).
그래서 말뭉치 목록을 여기 둔다.
DB 쪽 CHECK 제약(ORM 모델 db/models/chunks.py, 마이그레이션의 `^cite-idx-v[0-9]+$`)은
SQL 정규식이고 마이그레이션은 그때 모양으로 고정돼야 해서 따로 둔다.
"""

import re

# retrieval/schemas.py의 Corpus = Literal["law", "cite"]와 같아야 한다
# (tests/test_index_version.py가 맞춰 봄)
CORPORA: tuple[str, ...] = ("law", "cite")
_VERSION = re.compile(rf"^({'|'.join(CORPORA)})-idx-v([0-9]+)$")


def is_index_version(corpus: str, index_version: str) -> bool:
    """그 말뭉치의 판 이름 꼴이면 True (cite 표에 law-idx-v1 같은 것을 막는다)."""
    m = _VERSION.match(index_version)
    return m is not None and m.group(1) == corpus


def corpus_of(index_version: str) -> str | None:
    """판 이름 앞말의 말뭉치 (cite-idx-v2 → cite). 판 이름 꼴이 아니면 None."""
    m = _VERSION.match(index_version)
    return m.group(1) if m else None


def version_number(corpus: str, index_version: str) -> int | None:
    """그 말뭉치 판의 번호 (cite-idx-v10 → 10). 그 말뭉치 판 이름이 아니면 None."""
    m = _VERSION.match(index_version)
    return int(m.group(2)) if m and m.group(1) == corpus else None
