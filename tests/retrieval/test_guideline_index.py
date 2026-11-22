"""심사기준 조각 만들기 (이슈 #24 24b task-b1). 쪽 글은 지어낸 fixture만 쓴다 (원문 안 넣음)."""

import json
import logging
from datetime import date
from pathlib import Path

import pytest
import yaml

from patent_ai.retrieval.cite_index.pages import PageText
from patent_ai.retrieval.guideline_index import (
    Chapter,
    GuidelineIndexError,
    chapter_pages,
    chunk_guideline,
    guideline_editions,
    main,
)
from patent_ai.retrieval.schemas import Edition

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrieval" / "guideline"
CH = Chapter(part=3, chapter=3, title="진보성")
EDITION = Edition(
    status="confirmed", effective_from=date(2018, 1, 1), effective_to=None, label="가짜 예규"
)


def load_pages(name: str) -> list[PageText]:
    """fixture 파일 → 쪽 목록. 쪽은 `=====` 줄로 가른다 (실제 pdftotext는 form feed)."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [
        PageText(page=i, lines=chunk.splitlines())
        for i, chunk in enumerate(text.split("=====\n"), 1)
    ]


def chapter_chunks(name: str, doc_id: str = "심사기준_1_20180101", converted: bool = False):
    pages = load_pages(name)
    rng = chapter_pages(pages, CH)
    sub = [p for p in pages if p.page in rng]
    return chunk_guideline(sub, doc_id, EDITION, "law-idx-v3", CH, converted)


# ---- 장 범위 ----


def test_장_제목으로_쪽_범위를_찾고_빈_쪽은_안_끊고_다음_장에서_끝난다():
    # 목차 쪽(1)에는 "제3장 진보성"이 있어도 맨 위 줄이 아니라 건너뛰고, 2쪽부터 5쪽(빈 쪽 포함)까지
    assert chapter_pages(load_pages("edition_text.txt"), CH) == range(2, 6)


def test_장_제목을_못_찾으면_오류():
    with pytest.raises(GuidelineIndexError, match="장 제목"):
        chapter_pages(load_pages("edition_text.txt"), Chapter(3, 2, "신규성"))


def test_장_제목은_있어도_쪽_번호가_그_장이_아니면_못_찾은_것():
    # 제2부 제3장 진보성 (가상): 제목은 맞아도 쪽 번호 33xx가 아니라 23xx여야 한다
    with pytest.raises(GuidelineIndexError, match="장 제목"):
        chapter_pages(load_pages("edition_text.txt"), Chapter(2, 3, "진보성"))


# ---- 조각 ----


def test_절_둘이_한_쪽이면_조각_둘_절_하나가_두_쪽이면_쪽마다_조각():
    chunks = chapter_chunks("edition_text.txt")
    keys = [(c.location.start, c.attrs.get("section")) for c in chunks]
    # 3302쪽: 앞 쪽에서 이어진 1절, 2절, 2.1절 (절 둘 이상이 한 쪽) / 2.1절은 3303쪽에도 이어진다
    assert keys == [(3301, "1"), (3302, "1"), (3302, "2"), (3302, "2.1"), (3303, "2.1")]


def test_조각_글과_머리_꼬리말_버리기():
    chunks = chapter_chunks("edition_text.txt")
    by_id = {c.chunk_id.rsplit(":", 1)[1]: c for c in chunks}
    # 문단 안 줄은 공백 하나로, 문단은 줄바꿈으로 잇는다. 장 제목 줄(머리말·본문 안 되풀이)은 없다
    assert by_id["3301-1"].text == (
        "1. 가짜 관련 규정\n"
        "가짜 조문 첫째 줄이다. 시험용으로 지어낸 글이다.\n"
        "1. 인용된 호 번호는 들여쓰기가 있어 제목이 아니다 2. 인용된 둘째 호이다"
    )
    # 점 하나 숫자로 시작하는 본문 줄(1.5 배)은 제목이 아니라 앞 절 글에 남는다
    assert by_id["3302-1"].text == (
        "첫째 절 글이 다음 쪽에서 이어진다.\n"
        "1.5 배 이상이라는 숫자로 시작하는 본문 줄도 제목이 아니다."
    )
    assert by_id["3303-1"].text == "하위 절 본문의 뒷부분이다. 쪽을 넘어 이어진다.\n둘째 문단이다."
    for c in chunks:
        assert "제3부 특허요건" not in c.text
        assert "추록" not in c.text
        assert "제3장 진보성" not in c.text
        assert c.text.strip() != ""


def test_조각_칸과_loc_label():
    chunks = chapter_chunks("edition_text.txt")
    c = next(c for c in chunks if c.chunk_id.endswith(":3302-3"))
    assert c.chunk_id == "law-idx-v3:심사기준_1_20180101:3302-3"
    assert c.index_version == "law-idx-v3"
    assert c.doc_id == "심사기준_1_20180101"
    assert c.chunk_kind == "guideline"
    assert c.source_kind == "guideline"
    assert c.location.kind == "page"
    assert c.location.start == 3302 and c.location.end == 3302
    assert c.location.label == "3302쪽 (제3부 제3장 2.1)"
    assert c.edition == EDITION
    assert c.decided_on is None and c.speaker is None
    assert c.attrs == {"chapter": "진보성", "section": "2.1", "section_title": "2.1 가짜 하위 절"}


def test_변환본_판은_loc_label에_변환본_쪽을_붙인다():
    chunks = chapter_chunks("edition_text.txt", converted=True)
    assert chunks[0].location.label == "3301쪽 (변환본 쪽, 제3부 제3장 1)"


def test_절_제목이_그림인_판은_쪽_하나가_조각_하나이고_label에_절이_없다():
    chunks = chapter_chunks("edition_image.txt")
    assert [c.location.start for c in chunks] == [3301, 3302]
    assert [c.location.label for c in chunks] == ["3301쪽 (제3부 제3장)", "3302쪽 (제3부 제3장)"]
    assert all("section" not in (c.attrs or {}) for c in chunks)
    assert chunks[0].text == "그림 제목 아래의 첫 쪽 본문이다.\n다른 문단이다."


def test_장_범위_밖_쪽은_조각에_안_들어간다():
    for name in ("edition_text.txt", "edition_image.txt"):
        texts = " ".join(c.text for c in chapter_chunks(name))
        assert "다음 장 본문" not in texts
        assert "목차" not in texts


def test_같은_절_두_판은_chunk_id가_달라_둘_다_남는다():
    a = chapter_chunks("edition_text.txt", doc_id="심사기준_1_20180101")
    b = chapter_chunks("edition_text.txt", doc_id="심사기준_2_20190101")
    ids = [c.chunk_id for c in a + b]
    assert len(ids) == len(set(ids)) == 10


# ---- 판 표 ----


def test_시행_기간은_이어진다_앞_판_끝은_다음_판_시작_전날():
    table = [
        {"file": "c.pdf", "rule_no": 117, "effective_from": date(2020, 12, 14)},
        {"file": "a.pdf", "rule_no": 101, "effective_from": date(2018, 1, 1)},
        {
            "file": "b.pdf",
            "rule_no": 104,
            "effective_from": date(2018, 8, 1),
            "label": "지어낸 이름",
        },
    ]
    eds = guideline_editions(table)
    assert list(eds) == ["심사기준_101_20180101", "심사기준_104_20180801", "심사기준_117_20201214"]
    assert eds["심사기준_101_20180101"].effective_from == date(2018, 1, 1)
    assert eds["심사기준_101_20180101"].effective_to == date(2018, 7, 31)
    assert eds["심사기준_104_20180801"].effective_from == date(2018, 8, 1)
    assert eds["심사기준_104_20180801"].effective_to == date(2020, 12, 13)
    assert eds["심사기준_104_20180801"].label == "지어낸 이름"
    # 마지막 판은 끝일이 없다 (현행)
    assert eds["심사기준_117_20201214"].effective_to is None
    assert all(e.status == "confirmed" for e in eds.values())


def test_시행일이_같은_두_판은_오류():
    table = [
        {"file": "a.pdf", "rule_no": 1, "effective_from": date(2018, 1, 1)},
        {"file": "b.pdf", "rule_no": 2, "effective_from": date(2018, 1, 1)},
    ]
    with pytest.raises(GuidelineIndexError):
        guideline_editions(table)


# ---- 명령 ----


def _config(tmp_path: Path, files: dict[str, str], chapters=None) -> Path:
    cfg = {
        "index_version": "law-idx-v3",
        "raw_dir": str(tmp_path / "raw"),
        "out": str(tmp_path / "out" / "guideline-v3.jsonl"),
        "chapters": chapters or [{"part": 3, "chapter": 3, "title": "진보성"}],
        "editions": [
            {"file": f, "rule_no": i + 1, "effective_from": f"2018-0{i + 1}-01"}
            for i, f in enumerate(files)
        ],
    }
    path = tmp_path / "guidelines.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _fake_extract(mapping: dict[str, str]):
    # 파일 이름 → fixture 이름. PDF를 읽지 않고 지어낸 쪽 글을 돌려준다
    def extract(path):
        return load_pages(mapping[Path(path).name])

    return extract


MAPPING = {"a.pdf": "edition_text.txt", "b.pdf": "edition_image.txt"}


def test_명령은_판마다_조각_수를_찍고_jsonl을_쓴다(tmp_path, caplog):
    cfg = _config(tmp_path, {"a.pdf": 1, "b.pdf": 1})
    with caplog.at_level(logging.INFO):
        code = main(["--config", str(cfg)], extract=_fake_extract(MAPPING))
    assert code == 0
    out = tmp_path / "out" / "guideline-v3.jsonl"
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 7  # 글자 절 판 5 + 그림 절 판 2
    assert [r["chunk_id"] for r in rows] == sorted(r["chunk_id"] for r in rows)
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "심사기준_1_20180101: 쪽 4, 조각 5" in msgs
    assert "심사기준_2_20180201: 쪽 2, 조각 2" in msgs


def test_장을_못_찾는_판이_있으면_종료_1과_이유_파일은_안_만든다(tmp_path, caplog):
    cfg = _config(
        tmp_path, {"a.pdf": 1, "b.pdf": 1}, chapters=[{"part": 3, "chapter": 2, "title": "신규성"}]
    )
    code = main(["--config", str(cfg)], extract=_fake_extract(MAPPING))
    assert code == 1
    assert not (tmp_path / "out" / "guideline-v3.jsonl").exists()
    assert "장 제목을 못 찾았다" in caplog.text


def test_PDF가_없으면_종료_1(tmp_path, caplog):
    cfg = _config(tmp_path, {"missing.pdf": 1})
    assert main(["--config", str(cfg)]) == 1
    assert "PDF가 없다" in caplog.text


def test_같은_입력이면_같은_바이트이고_있는_출력은_덮지_않는다(tmp_path):
    cfg = _config(tmp_path, {"a.pdf": 1, "b.pdf": 1})
    out = tmp_path / "out" / "guideline-v3.jsonl"
    assert main(["--config", str(cfg)], extract=_fake_extract(MAPPING)) == 0
    first = out.read_bytes()
    # 이미 있으면 멈춘다 (종료 1), 파일은 그대로
    assert main(["--config", str(cfg)], extract=_fake_extract(MAPPING)) == 1
    assert out.read_bytes() == first
    # --force로 다시 만들면 같은 바이트
    assert main(["--config", str(cfg), "--force"], extract=_fake_extract(MAPPING)) == 0
    assert out.read_bytes() == first
