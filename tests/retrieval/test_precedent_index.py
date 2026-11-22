"""판례·심결 청커 테스트 (#24 24c). 입력은 지어낸 글이다 (원문을 넣지 않는다)."""

import json
import logging
from datetime import date
from pathlib import Path

import pytest
import yaml

from patent_ai.db.models.chunks import check_law_chunk
from patent_ai.retrieval.precedent_index import (
    PrecedentIndexError,
    chunk_precedent,
    classify_heading,
    main,
    select_precedents,
)
from patent_ai.retrieval.schemas import Chunk

V = "law-idx-v3"
FIX = Path(__file__).parent.parent / "fixtures" / "retrieval" / "precedent"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _by_id(chunks: list[Chunk]) -> dict[str, Chunk]:
    return {c.chunk_id.split(":", 2)[2]: c for c in chunks}


def test_요지_칸마다_조각_하나씩_법원이_말한_것():
    chunks = chunk_precedent(_load("patent_court.json"), V)
    summaries = [c for c in chunks if c.chunk_kind == "judgment_summary"]
    assert [c.location.label for c in summaries] == [
        "판시사항 [1]",
        "판시사항 [2]",
        "판결요지 [1]",
        "판결요지 [2]",
    ]
    assert {c.speaker for c in summaries} == {"court"}
    assert summaries[2].text == "지어낸 요지 첫째 법리이다."
    assert summaries[0].chunk_id == "law-idx-v3:판례_2099허1001:s1"


def test_이유_번호_문단마다_조각_문장속_목록과_서명은_안_가름():
    chunks = chunk_precedent(_load("patent_court.json"), V)
    reasons = _by_id([c for c in chunks if c.chunk_kind == "judgment"])
    assert [c.location.label for c in reasons.values()] == [
        "이유 1. 가.",
        "이유 1. 나.",
        "이유 2. 가.",
        "이유 2. 나.",
        "이유 3. 가.",
        "이유 3. 나.",
        "이유 4.",
    ]
    # 제목뿐인 1단계 줄은 따로 조각이 되지 않고 아래 조각 글 앞에 붙는다
    assert reasons["r1-1"].text == "1. 심결의 경위\n가. 출원\n지어낸 출원 경위 글이다."
    # 번호가 이어지지 않는 "1. 문장 속 목록"은 앞 조각 글이다
    assert "2. 문장 속 목록 둘" in reasons["r3-1"].text
    # 판결 끝 서명 줄은 뺀다
    assert "판사" not in reasons["r4-0"].text


def test_당사자_주장_판단_모름을_제목으로_가름():
    chunks = chunk_precedent(_load("patent_court.json"), V)
    sp = {k: c.speaker for k, c in _by_id(chunks).items() if k.startswith("r")}
    assert sp["r1-1"] == "unknown"  # 경위
    assert sp["r2-1"] == "party"  # 원고의 주장
    assert sp["r2-2"] == "party"  # 피고의 주장
    assert sp["r3-1"] == "court"  # 법리
    assert sp["r3-2"] == "court"  # 구체적 판단
    assert sp["r4-0"] == "court"  # 결론


def test_제목이_없는_글은_대법원만_법원_나머지는_모름():
    chunks = _by_id(chunk_precedent(_load("supreme_no_summary.json"), V))
    assert "r0-0" not in chunks  # "상고이유를 본다." 한 마디 머리말은 조각을 만들지 않는다
    assert chunks["r1-0"].speaker == "court"  # 긴 줄은 제목이 아니라 문단
    assert chunks["r3-0"].speaker == "unknown"  # 쟁점 정리
    other = _load("supreme_no_summary.json")
    other["PrecService"]["법원명"] = "특허법원"
    other["PrecService"]["판례내용"] = other["PrecService"]["판례내용"].replace(
        "2. 상고이유 제1점에 대하여", "2. 사건 정리"
    )
    chunks2 = _by_id(chunk_precedent(other, V))
    assert chunks2["r1-0"].speaker == "unknown"
    assert chunks2["r2-0"].speaker == "unknown"


def test_요지_없는_판례는_전문만():
    chunks = chunk_precedent(_load("supreme_no_summary.json"), V)
    assert {c.chunk_kind for c in chunks} == {"judgment"}
    assert len(chunks) == 3


def test_선고일_못_읽으면_null과_경고(caplog):
    with caplog.at_level(logging.WARNING):
        chunks = chunk_precedent(_load("supreme_no_summary.json"), V)
    assert {c.decided_on for c in chunks} == {None}
    assert "2099후2002" in caplog.text


def test_메타와_br_정리_그리고_법령_표_검사를_통과():
    chunks = chunk_precedent(_load("patent_court.json"), V)
    assert all("<br/>" not in c.text for c in chunks)
    for c in chunks:
        assert c.doc_id == "판례_2099허1001"
        assert c.decided_on == date(2099, 12, 31)
        assert c.source_kind == "precedent"
        assert c.edition.status == "not_applicable"
        assert c.location.kind == "paragraph"
        assert c.attrs == {"법원명": "특허법원", "사건명": "거절결정(특)", "사건종류": "특허"}
        assert (
            check_law_chunk(c.chunk_kind, c.edition.status, c.source_kind, c.decided_on, c.speaker)
            is None
        )
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_이유_제목_없으면_오류():
    data = _load("patent_court.json")
    data["PrecService"]["판례내용"] = "【주    문】 기각"
    with pytest.raises(PrecedentIndexError):
        chunk_precedent(data, V)


def _rec(
    path: str, topic: str, status: str = "ok", name: str = "거절결정(특)", mark: str | None = None
):
    r = {"topic": topic, "사건명": name, "path": f"data/raw/prec/{path}", "status": status}
    if mark:
        r["표시"] = mark
    return r


def test_뺄_판례_거르기():
    log1 = [
        _rec("body_a.json", "진보성"),
        _rec("body_b.json", "명확성"),
        _rec("body_x.json", "명확성", status="실패"),  # 못 받은 것
    ]
    log2 = [
        _rec("body_c.json", "신규성"),  # 신규성 맞음
        _rec("body_d.json", "신규성"),  # 아래 v2에서 표시됨 → 뺌
        _rec("body_a.json", "신규성", status="dup"),
        _rec("body_e.json", "신규성", name="거절결정(상)"),  # 상표 → 뺌
        _rec("body_f.json", "신규성", name="등록무효(디)"),  # 디자인 → 뺌
    ]
    v2 = [
        _rec("body_d.json", "신규성", mark="신규성 아님(진보성 등)"),
        # 표시가 붙었어도 진보성 기록에서 이미 받은 사건은 그 주제 판례라 남긴다
        _rec("body_a.json", "신규성", status="dup", mark="신규성 아님(진보성 등)"),
        _rec("body_c.json", "신규성"),
    ]
    assert select_precedents([log1, log2, v2], expected=3) == [
        "body_a.json",
        "body_b.json",
        "body_c.json",
    ]


def test_건수가_설정과_다르면_멈춤():
    with pytest.raises(PrecedentIndexError, match="1건"):
        select_precedents([[_rec("body_a.json", "진보성")]], expected=74)


def _config(tmp_path: Path, expected: int) -> Path:
    raw = tmp_path / "prec"
    raw.mkdir()
    for name in ("patent_court.json", "supreme_no_summary.json"):
        (raw / f"body_{name}").write_text(
            (FIX / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    log = [_rec("body_patent_court.json", "진보성"), _rec("body_supreme_no_summary.json", "명확성")]
    (raw / "log.json").write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
    cfg = {
        "index_version": V,
        "precedent_dir": str(raw),
        "precedent_logs": ["log.json"],
        "expected_precedents": expected,
        "out": str(tmp_path / "out" / "precedent-v3.jsonl"),
    }
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def test_명령_같은_입력_같은_바이트_있으면_멈춤_force로_덮음(tmp_path):
    cfg = _config(tmp_path, expected=2)
    out = Path(yaml.safe_load(cfg.read_text(encoding="utf-8"))["out"])
    assert main(["--config", str(cfg)]) == 0
    first = out.read_bytes()
    assert main(["--config", str(cfg)]) == 1  # 이미 있음
    assert out.read_bytes() == first
    assert main(["--config", str(cfg), "--force"]) == 0
    assert out.read_bytes() == first
    ids = [json.loads(line)["chunk_id"] for line in first.decode().splitlines()]
    assert ids == sorted(ids)


def test_명령_건수가_다르면_종료_1과_파일_없음(tmp_path):
    cfg = _config(tmp_path, expected=74)
    assert main(["--config", str(cfg)]) == 1
    assert not Path(yaml.safe_load(cfg.read_text(encoding="utf-8"))["out"]).exists()


@pytest.mark.parametrize(
    ("heading", "speaker"),
    [
        ("가. 원고의 주장", "party"),
        ("나. 피고 주장의 요지", "party"),
        ("3. 판 단", "court"),
        ("4. 이 사건 발명의 진보성 여부", "court"),
        ("1. 기초사실", "unknown"),
        ("2) 주장과 판단", "unknown"),  # 주장과 판단이 섞인 제목
        ("가. 이 사건 출원발명", "unknown"),
        ("가. 특허법 제42조의 해석", None),  # 제목으로 못 정함 -> 위 단계 제목을 따름
    ],
)
def test_제목_한_줄의_발언_주체(heading, speaker):
    assert classify_heading(heading) == speaker
