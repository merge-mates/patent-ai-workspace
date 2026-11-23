"""law-idx-v3 빌드 테스트 (#24 24d). 글은 모두 지어낸 것이다."""

import json
from datetime import date

import pytest
import yaml

from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.law_index import build_index, write_jsonl
from patent_ai.retrieval.law_v3 import main, merge_parts
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

V = "law-idx-v3"
NA = Edition(status="not_applicable")
GUIDE = Edition(status="confirmed", effective_from=date(2018, 1, 1), label="가짜 예규")


def _chunk(doc_id, kind, source, edition, version=V, **extra) -> Chunk:
    return Chunk(
        chunk_id=f"{version}:{doc_id}:1",
        index_version=version,
        doc_id=doc_id,
        chunk_kind=kind,
        location=Location(kind="paragraph", start=1, end=1, label="이유 1."),
        edition=edition,
        text="지어낸 글",
        source_kind=source,
        **extra,
    )


def _guideline(version=V):
    return _chunk("심사기준_1_20180101", "guideline", "guideline", GUIDE, version)


def _precedent():
    return _chunk(
        "판례_2099후1", "judgment", "precedent", NA, decided_on=date(2019, 1, 1), speaker="court"
    )


def _trial():
    return _chunk(
        "심결_2099원1", "judgment", "trial", NA, decided_on=date(2019, 1, 1), speaker="unknown"
    )


def _law_json(day):
    return {
        "법령": {
            "기본정보": {"시행일자": day},
            "조문": {
                "조문단위": [
                    {"조문여부": "조문", "조문번호": "29", "조문내용": "제29조(요건) 지어낸 글"}
                ]
            },
        }
    }


def _config(tmp_path, parts=None, **over):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    for mst, day in (("1", "20180101"), ("2", "20200101")):
        (raw / f"body_특허법_{mst}_{day}.json").write_text(
            json.dumps(_law_json(day), ensure_ascii=False), encoding="utf-8"
        )
    paths = []
    for i, chunks in enumerate(parts or [[_guideline()], [_precedent(), _trial()]]):
        p = tmp_path / f"part{i}.jsonl"
        p.unlink(missing_ok=True)
        write_jsonl(chunks, p)
        paths.append(str(p))
    cfg = {
        "index_version": V,
        "raw_dir": str(raw),
        "laws": ["특허법"],
        "parts": paths,
        "out": str(tmp_path / "v3.jsonl"),
        "missing_editions": {"특허법": [date(2019, 3, 1)]},
        **over,
    }
    path = tmp_path / "v3.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def test_네_자료_유형이_한_판으로_모이고_조문은_v1_청커와_같다(tmp_path):
    assert main(["--config", str(_config(tmp_path))]) == 0
    repo = InMemoryChunkRepository.from_jsonl("law", tmp_path / "v3.jsonl")
    assert repo.count_chunks("law", V) == 5
    for kind, n in (("statute", 2), ("guideline", 1), ("precedent", 1), ("trial", 1)):
        assert repo.count_chunks("law", V, source_kinds=[kind]) == n
    got = repo.chunks("law", V, source_kinds=["statute"])
    same = build_index(tmp_path / "raw", ["특허법"], V)[0]
    assert {(c.chunk_id, c.text) for c in got} == {(c.chunk_id, c.text) for c in same}
    # 받지 못한 판 설정이 먹는다: 2019.3.1~2019.12.31에는 시행 중인 조문이 없다
    assert repo.chunks("law", V, as_of=date(2019, 6, 1), source_kinds=["statute"]) == []


@pytest.mark.parametrize("gone", ["guideline", "precedent", "trial"])
def test_자료_유형이_0개면_파일을_만들지_않고_1로_끝난다(tmp_path, gone, caplog):
    parts = [c for c in (_guideline(), _precedent(), _trial()) if c.source_kind != gone]
    assert main(["--config", str(_config(tmp_path, [parts]))]) == 1
    assert not (tmp_path / "v3.jsonl").exists()
    assert gone in caplog.text


def test_다른_판이나_겹친_조각이_섞이면_멈춘다():
    ok = [_precedent(), _trial()]
    with pytest.raises(RetrievalError, match="law-idx-v4"):
        merge_parts([ok, [_guideline("law-idx-v4")]], V)
    with pytest.raises(RetrievalError, match="겹친다"):
        merge_parts([ok, ok], V)


def test_입력_파일이_없거나_출력이_있으면_1로_끝난다(tmp_path):
    cfg = _config(tmp_path, parts=None)
    (tmp_path / "part0.jsonl").unlink()
    assert main(["--config", str(cfg)]) == 1
    cfg = _config(tmp_path)
    (tmp_path / "v3.jsonl").write_text("old", encoding="utf-8")
    assert main(["--config", str(cfg)]) == 1
    assert (tmp_path / "v3.jsonl").read_text(encoding="utf-8") == "old"


def test_설정_키가_빠지면_1로_끝난다(tmp_path):
    assert main(["--config", str(_config(tmp_path, laws=[]))]) == 1


def test_같은_입력이면_같은_바이트(tmp_path):
    main(["--config", str(_config(tmp_path))])
    first = (tmp_path / "v3.jsonl").read_bytes()
    main(["--config", str(_config(tmp_path, out=str(tmp_path / "b.jsonl")))])
    assert (tmp_path / "b.jsonl").read_bytes() == first
