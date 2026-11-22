"""색인 판 이름 `<말뭉치>-idx-v<N>` 또는 `<말뭉치>-idx-us<N>` 규칙 하나.
(예: law-idx-v2, cite-idx-us1)

- v 줄: 지금까지의 판 (DB에 들어가는 판).
- us 줄: 미국 공보 청킹을 넣은 인용문헌(cite) 판만 (이슈 #308, 예: cite-idx-us1).
  다른 사람의 v 줄 번호와 겹치지 않게 따로 센다.
  us 판은 번호(version_number)를 돌려주지 않는다. 덤프 이름(db/index_dump)은 v 줄 번호로만 짓는다.
  DB 표의 CHECK 제약이 아직 `^cite-idx-v[0-9]+$`라서, us 판을 Postgres에 넣으면 CHECK에서
  바로 실패한다 (조용히 들어가지 않는다). 그래서 DB에 넣기 전 검사는
  is_db_index_version(v 줄만)을 쓴다. 넣으려면 마이그레이션으로 CHECK를 넓혀야 하고,
  그건 사람이 정한다. 그 전에는 jsonl·메모리 저장소(eval --chunks)로만 쓴다.

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
# v 줄은 모든 말뭉치, us 줄은 cite만 (미국 공보 청킹은 인용문헌 색인에만 있다)
# 그룹: 1 말뭉치(v 줄) 2 번호(v 줄) 3 말뭉치(us 줄, cite) 4 번호(us 줄)
_VERSION = re.compile(rf"^(?:({'|'.join(CORPORA)})-idx-v([0-9]+)|(cite)-idx-us([0-9]+))$")
# DB 표 CHECK와 같은 범위: v 줄만
_DB_VERSION = re.compile(rf"^({'|'.join(CORPORA)})-idx-v([0-9]+)$")


def is_index_version(corpus: str, index_version: str) -> bool:
    """그 말뭉치의 판 이름 꼴이면 True (cite 표에 law-idx-v1 같은 것을 막는다)."""
    m = _VERSION.match(index_version)
    return m is not None and (m.group(1) or m.group(3)) == corpus


def is_db_index_version(corpus: str, index_version: str) -> bool:
    """DB 표에 넣을 수 있는 판 이름이면 True (표 CHECK `^cite-idx-v[0-9]+$`와 같은 범위, v 줄만)."""
    m = _DB_VERSION.match(index_version)
    return m is not None and m.group(1) == corpus


def corpus_of(index_version: str) -> str | None:
    """판 이름 앞말의 말뭉치 (cite-idx-v2 → cite). 판 이름 꼴이 아니면 None."""
    m = _VERSION.match(index_version)
    return (m.group(1) or m.group(3)) if m else None


def version_number(corpus: str, index_version: str) -> int | None:
    """그 말뭉치 v 줄 판의 번호 (cite-idx-v10 → 10). 그 말뭉치 판 이름이 아니거나 us 줄이면 None."""
    m = _VERSION.match(index_version)
    # us 줄은 group 1·2가 비어 있어 None (덤프 이름 번호 비교에 안 섞인다)
    return int(m.group(2)) if m and m.group(1) == corpus else None
