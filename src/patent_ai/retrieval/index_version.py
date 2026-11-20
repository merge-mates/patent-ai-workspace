"""색인 판 이름 `<말뭉치>-idx-v<N>` 규칙 하나 (예: law-idx-v2, cite-idx-v2).

넣기(law_index_db), 메모리 저장소(repository), 벡터 채우기(core/index_embed),
법령 색인(law_index)이 같이 쓴다.
DB 덤프(db/index_dump)와 마이그레이션 CHECK 제약은 db가 retrieval을 import하지 않아 따로 둔다.
"""

import re
from typing import get_args

from patent_ai.retrieval.schemas import Corpus

CORPORA: tuple[str, ...] = get_args(Corpus)  # ("law", "cite")
_VERSION = re.compile(rf"^({'|'.join(CORPORA)})-idx-v[0-9]+$")


def is_index_version(corpus: str, index_version: str) -> bool:
    """그 말뭉치의 판 이름 꼴이면 True (cite 표에 law-idx-v1 같은 것을 막는다)."""
    m = _VERSION.match(index_version)
    return m is not None and m.group(1) == corpus


def corpus_of(index_version: str) -> str | None:
    """판 이름 앞말의 말뭉치 (cite-idx-v2 → cite). 판 이름 꼴이 아니면 None."""
    m = _VERSION.match(index_version)
    return m.group(1) if m else None
