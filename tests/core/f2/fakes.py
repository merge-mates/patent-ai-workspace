"""F2 테스트용 지어낸 법령 조각 (진짜 법령 글이 아니다). 색인 판은 law-idx-v2 꼴."""

from datetime import date

from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "law-idx-v2"
OLD_DOC, NEW_DOC = "특허법_1001_20150101", "특허법_1002_20200101"
DECREE_DOC = "특허법_시행령_2001_20200101"  # 같은 위치 번호라도 시행령은 다른 법
OLD = Edition(
    status="confirmed",
    effective_from=date(2015, 1, 1),
    effective_to=date(2019, 12, 31),
    label=OLD_DOC,
)
NEW = Edition(status="confirmed", effective_from=date(2020, 1, 1), label=NEW_DOC)

TEXT_292_OLD = "제29조(특허요건) ② 구판 진보성 가짜 조문 글"
TEXT_292_NEW = "제29조(특허요건) ② 신판 진보성 가짜 조문 글 통상의 기술자"
TEXT_424_NEW = "제42조(특허출원) ④ 신판 명확성 가짜 조문 글 2. 발명이 명확할 것"


def law_chunk(doc_id: str, loc: int, label: str, text: str, edition: Edition, kind="article"):
    return Chunk(
        chunk_id=f"{IV}:{doc_id}:{loc}",
        index_version=IV,
        doc_id=doc_id,
        chunk_kind=kind,
        location=Location(kind="article", start=loc, end=loc, label=label),
        edition=edition,
        text=text,
    )


def chunks() -> list[Chunk]:
    return [
        law_chunk(OLD_DOC, 290002, "제29조제2항", TEXT_292_OLD, OLD),
        law_chunk(NEW_DOC, 290002, "제29조제2항", TEXT_292_NEW, NEW),
        law_chunk(NEW_DOC, 420004, "제42조제4항", TEXT_424_NEW, NEW),
        law_chunk(DECREE_DOC, 290002, "제29조제2항", "시행령 가짜 글", NEW),
    ]


def repo(extra: list[Chunk] = ()) -> InMemoryChunkRepository:
    return InMemoryChunkRepository({"law": [*chunks(), *extra]})
