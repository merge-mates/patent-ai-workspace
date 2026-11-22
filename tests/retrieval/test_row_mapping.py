"""칸 매핑이 두 곳(db.index_dump, retrieval.repository)에 있어 어긋나지 않는지 본다."""

from pathlib import Path

import pytest

from patent_ai.db.index_dump import fixture_rows
from patent_ai.retrieval.repository import InMemoryChunkRepository, chunk_to_row

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrieval"
# created_at 같은 DB 기본값 칸은 빼고 비교한다
SKIP = {"created_at", "updated_at"}


def _values(row):
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key not in SKIP}


@pytest.mark.parametrize("corpus", ["cite", "law"])
def test_fixture_rows와_chunk_to_row의_칸_값이_같다(corpus):
    path = FIXTURES / f"chunks_{corpus}.jsonl"
    a = fixture_rows(corpus, path.read_text(encoding="utf-8"))
    repo = InMemoryChunkRepository.from_jsonl(corpus, path)
    b = [chunk_to_row(corpus, c) for c in repo._tables[corpus]]
    assert a and len(a) == len(b)
    assert [_values(r) for r in a] == [_values(r) for r in b]


# ---- 법령 표 새 칸 넷 (#24 24a) ----
def _precedent_chunk(**over):
    d = {
        "chunk_id": "law-idx-v3:판례_1:요지",
        "index_version": "law-idx-v3",
        "doc_id": "판례_1",
        "chunk_kind": "judgment_summary",
        "location": {"kind": "paragraph", "label": "요지"},
        "edition": {"status": "confirmed", "effective_from": "2021-05-13"},
        "text": "가짜 요지",
        "source_kind": "precedent",
        "decided_on": "2021-05-13",
        "speaker": "court",
        "attrs": {"court": "대법원"},
    }
    d.update(over)
    return d


def _write(tmp_path, *chunks):
    import json

    path = tmp_path / "v3.jsonl"
    path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks), "utf-8")
    return path


def test_새_칸이_메모리_행_변환_덤프_fixture를_왕복한다(tmp_path):
    from patent_ai.retrieval.repository import row_to_chunk

    path = _write(tmp_path, _precedent_chunk())
    chunk = InMemoryChunkRepository.from_jsonl("law", path)._tables["law"][0]
    row = chunk_to_row("law", chunk)
    assert (row.source_kind, row.speaker, row.attrs) == ("precedent", "court", {"court": "대법원"})
    assert row.decided_on.isoformat() == "2021-05-13"
    assert row_to_chunk(row) == chunk  # 행 -> 조각 왕복
    # 덤프 fixture 경로도 같은 행 값
    (fx,) = fixture_rows("law", path.read_text(encoding="utf-8"))
    assert _values(fx) == _values(row)


def test_옛_JSONL은_source_kind가_없어도_statute로_읽는다():
    # v1 fixture에는 새 칸이 없다. law는 모두 statute, 나머지 새 칸은 비어 있다
    path = FIXTURES / "chunks_law.jsonl"
    chunks = InMemoryChunkRepository.from_jsonl("law", path)._tables["law"]
    assert chunks and {c.source_kind for c in chunks} == {"statute"}
    assert {(c.decided_on, c.speaker, c.attrs) for c in chunks} == {(None, None, None)}
    rows = fixture_rows("law", path.read_text(encoding="utf-8"))
    assert {r.source_kind for r in rows} == {"statute"}


def test_인용문헌_조각은_새_칸이_비어_있다():
    path = FIXTURES / "chunks_cite.jsonl"
    chunks = InMemoryChunkRepository.from_jsonl("cite", path)._tables["cite"]
    assert all(
        (c.source_kind, c.decided_on, c.speaker, c.attrs) == (None, None, None, None)
        for c in chunks
    )
    for r in fixture_rows("cite", path.read_text(encoding="utf-8")):
        assert not hasattr(r, "source_kind")


def test_v2_JSONL을_다시_넣어도_마이그레이션으로_채운_DB와_내용_지문이_같다():
    # 마이그레이션은 옛 행에 statute만 채우므로, DB에서 읽은 조각 = 새 칸 비고 statute인 조각이다
    from patent_ai.retrieval.law_index_db import content_sha256, read_chunks_jsonl
    from patent_ai.retrieval.repository import row_to_chunk

    path = FIXTURES / "chunks_law.jsonl"
    from_file = read_chunks_jsonl(path, "law")
    old = InMemoryChunkRepository.from_jsonl("law", path)._tables["law"]
    db_like = [
        row_to_chunk(chunk_to_row("law", c.model_copy(update={"source_kind": "statute"})))
        for c in old
    ]
    assert content_sha256(from_file) == content_sha256(db_like)
    assert {c.source_kind for c in from_file} == {"statute"}


# ---- 판례·심결 not_applicable 허용과 거부 (세 곳이 같은 검사 함수를 쓴다, #24 24a) ----
def _na_precedent(**over):
    return _precedent_chunk(edition={"status": "not_applicable"}, **over)


def test_판례_조각_not_applicable은_세_곳_모두_통과한다(tmp_path):
    from patent_ai.retrieval.law_index_db import _check

    path = _write(tmp_path, _na_precedent())
    chunks = InMemoryChunkRepository.from_jsonl("law", path)._tables["law"]  # 저장소
    _check(chunks, "law", "law-idx-v3")  # 넣기
    assert fixture_rows("law", path.read_text(encoding="utf-8"))  # 덤프
    assert chunks[0].edition.status == "not_applicable"
    assert chunks[0].chunk_kind == "judgment_summary"


@pytest.mark.parametrize("kind", ["judgment", "judgment_summary"])
def test_심결_judgment도_not_applicable을_넣을_수_있다(tmp_path, kind):
    path = _write(tmp_path, _na_precedent(chunk_kind=kind, source_kind="trial"))
    assert InMemoryChunkRepository.from_jsonl("law", path)._tables["law"]


@pytest.mark.parametrize("kind", ["article", "guideline"])
def test_조문_심사기준_조각_not_applicable은_세_곳_모두_거부한다(tmp_path, kind):
    from patent_ai.db.index_dump import IndexDumpError
    from patent_ai.retrieval.law_index_db import IndexDbError, _check
    from patent_ai.retrieval.schemas import Chunk

    bad = _na_precedent(chunk_kind=kind, source_kind="statute", decided_on=None, speaker=None)
    path = _write(tmp_path, bad)
    with pytest.raises(ValueError, match=r"v3\.jsonl:1"):  # 저장소
        InMemoryChunkRepository.from_jsonl("law", path)
    with pytest.raises(IndexDbError):  # 넣기
        _check([Chunk.model_validate(bad)], "law", "law-idx-v3")
    with pytest.raises(IndexDumpError):  # 덤프
        fixture_rows("law", path.read_text(encoding="utf-8"))


def test_선고일은_판례_심결_조각만_가진다(tmp_path):
    from patent_ai.db.index_dump import IndexDumpError

    for field, value in (("decided_on", "2020-01-01"), ("speaker", "court")):
        bad = _precedent_chunk(source_kind="statute", decided_on=None, speaker=None)
        bad[field] = value
        path = _write(tmp_path, bad)
        with pytest.raises(ValueError):
            InMemoryChunkRepository.from_jsonl("law", path)
        with pytest.raises(IndexDumpError):
            fixture_rows("law", path.read_text(encoding="utf-8"))


def test_인용문헌_조각에_새_칸을_넣으면_세_곳_모두_거부한다(tmp_path):
    import json

    from patent_ai.db.index_dump import IndexDumpError
    from patent_ai.retrieval.law_index_db import IndexDbError, _check
    from patent_ai.retrieval.schemas import Chunk

    line = json.loads((FIXTURES / "chunks_cite.jsonl").read_text(encoding="utf-8").splitlines()[0])
    line["source_kind"] = "statute"
    path = _write(tmp_path, line)
    with pytest.raises(ValueError):
        InMemoryChunkRepository.from_jsonl("cite", path)
    with pytest.raises(IndexDbError):
        _check([Chunk.model_validate(line)], "cite", "cite-idx-v1")
    with pytest.raises(IndexDumpError):
        fixture_rows("cite", path.read_text(encoding="utf-8"))


def test_attrs_키_순서만_달라도_내용_해시가_같다():
    # JSONB는 키를 다시 정렬해 돌려주므로 해시가 키 순서를 타면 다시 넣기가 멈춘다
    from patent_ai.retrieval.law_index_db import content_sha256
    from patent_ai.retrieval.schemas import Chunk

    a = Chunk.model_validate(_precedent_chunk(attrs={"court": "대법원", "case": "2020후1"}))
    b = Chunk.model_validate(_precedent_chunk(attrs={"case": "2020후1", "court": "대법원"}))
    assert content_sha256([a]) == content_sha256([b])


def test_chunk_to_row는_source_kind가_빈_law_조각을_statute로_채운다():
    from patent_ai.retrieval.schemas import Chunk

    c = Chunk.model_validate(_precedent_chunk(source_kind=None, decided_on=None, speaker=None))
    assert chunk_to_row("law", c).source_kind == "statute"
