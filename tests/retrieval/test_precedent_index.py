"""판례·심결 청커 테스트 (#24 24c). 입력은 지어낸 글이다 (원문을 넣지 않는다)."""

import json
import logging
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from patent_ai.db.models.chunks import check_law_chunk
from patent_ai.retrieval import precedent_index
from patent_ai.retrieval.precedent_index import (
    PrecedentIndexError,
    chunk_precedent,
    chunk_trial,
    classify_heading,
    main,
    pack_lines,
    select_precedents,
    split_numbered,
    trial_doc_id,
)
from patent_ai.retrieval.schemas import Chunk

V = "law-idx-v3"
FIX = Path(__file__).parent.parent / "fixtures" / "retrieval" / "precedent"
TRIAL_FIX = Path(__file__).parent.parent / "fixtures" / "retrieval" / "trial"
TRIAL_FILE = "2099101001234.pdf"


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
        "이유 3. 나. 1)",
        "이유 3. 나. 2)",
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
    assert sp["r3-2-1"] == "party"  # 판단 아래 "1) 원고의 주장"은 court에 섞이지 않는다
    assert sp["r3-2-2"] == "court"
    assert sp["r4-0"] == "court"  # 결론
    # 3단계 조각은 위 단계 제목을 앞에 붙인다
    by = _by_id(chunks)
    assert (
        by["r3-2-1"].text
        == "3. 판 단\n나. 구체적 판단\n1) 원고의 주장\n지어낸 원고 주장 재언급 글이다."
    )


def test_제목이_없는_글은_법원이_대법원이어도_모름():
    chunks = _by_id(chunk_precedent(_load("supreme_no_summary.json"), V))
    assert "r0-0" not in chunks  # "상고이유를 본다." 한 마디 머리말은 조각을 만들지 않는다
    assert chunks["r1-0"].speaker == "unknown"  # 긴 줄은 제목이 아니라 문단, 제목 없음 → unknown
    assert chunks["r2-0"].speaker == "court"  # 상고이유에 대하여
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


def _config(tmp_path: Path, expected: int, expected_trials: int = 1) -> Path:
    # 심결 PDF는 빈 파일 하나만 두고, 글 읽기는 테스트에서 가짜로 바꾼다
    trials = tmp_path / "trials"
    (trials / "진보성만").mkdir(parents=True)
    (trials / "진보성만" / TRIAL_FILE).write_bytes(b"")
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
        "trial_dir": str(trials),
        "expected_trials": expected_trials,
        "out": str(tmp_path / "out" / "precedent-v3.jsonl"),
    }
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def _fake_pdf(monkeypatch):
    monkeypatch.setattr(precedent_index, "read_trial_pages", lambda _path: _trial_pages())


def test_명령_같은_입력_같은_바이트_있으면_멈춤_force로_덮음(tmp_path, monkeypatch):
    _fake_pdf(monkeypatch)
    cfg = _config(tmp_path, expected=2)
    out = Path(yaml.safe_load(cfg.read_text(encoding="utf-8"))["out"])
    assert main(["--config", str(cfg)]) == 0
    first = out.read_bytes()
    assert main(["--config", str(cfg)]) == 1  # 이미 있음
    assert out.read_bytes() == first
    assert main(["--config", str(cfg), "--force"]) == 0
    assert out.read_bytes() == first
    rows = [json.loads(line) for line in first.decode().splitlines()]
    ids = [r["chunk_id"] for r in rows]
    assert ids == sorted(ids)
    # 판례 둘 + 심결 하나가 한 파일에 들어간다
    assert {r["doc_id"] for r in rows} == {"판례_2099허1001", "판례_2099후2002", "심결_2099원1234"}
    assert {r["source_kind"] for r in rows} == {"precedent", "trial"}


def test_명령_건수가_다르면_종료_1과_파일_없음(tmp_path, monkeypatch):
    _fake_pdf(monkeypatch)
    cfg = _config(tmp_path, expected=74)
    assert main(["--config", str(cfg)]) == 1
    assert not Path(yaml.safe_load(cfg.read_text(encoding="utf-8"))["out"]).exists()


def test_명령_심결_건수가_다르면_종료_1(tmp_path, monkeypatch):
    _fake_pdf(monkeypatch)
    cfg = _config(tmp_path, expected=2, expected_trials=12)
    assert main(["--config", str(cfg)]) == 1
    assert not Path(yaml.safe_load(cfg.read_text(encoding="utf-8"))["out"]).exists()


# ---------- 심결 (task-c2) ----------


def _trial_pages() -> list[str]:
    return [(TRIAL_FIX / f"page{i}.txt").read_text(encoding="utf-8") for i in (1, 2)]


def test_심판번호는_파일_이름_13자리에서(tmp_path):
    assert trial_doc_id("2026101000634.pdf") == "심결_2026원634"
    assert trial_doc_id("2016101007372.pdf") == "심결_2016원7372"
    assert trial_doc_id("2099101001234.pdf") == "심결_2099원1234"
    for bad in ("abc.pdf", "202610100063.pdf", "2026102000634.pdf"):  # 자리 수·종류 코드가 다름
        with pytest.raises(PrecedentIndexError):
            trial_doc_id(bad)


def test_심결_이유_번호_문단마다_조각_쪽을_넘는_문단은_이어붙임():
    chunks = chunk_trial(_trial_pages(), TRIAL_FILE, V, trial_type="진보성만")
    by = _by_id(chunks)
    assert list(by) == ["r1-1", "r1-2", "r2-0", "r3-1", "r3-1-1", "r3-1-2", "r3-2", "r4-0"]
    assert [c.location.label for c in chunks] == [
        "이유 1. 가.",
        "이유 1. 나.",
        "이유 2.",
        "이유 3. 가.",
        "이유 3. 가. 1)",
        "이유 3. 가. 2)",
        "이유 3. 나.",
        "이유 4.",
    ]
    assert by["r1-1"].text.startswith(
        "1. 기초사실\n가. 절차의 경위\n① 특허출원 : 2099. 1. 1.\n② 거절결정"
    )
    # 쪽 바닥에서 끊긴 문장은 다음 쪽 글과 이어진다, 쪽 번호 줄은 없다
    assert "끝나지 않고 쪽을 넘어서 이어진다." in by["r2-0"].text
    assert "1/2" not in by["r2-0"].text
    # 번호가 이어지지 않는 "1. 문장 속 목록"은 앞 조각 글이다
    assert "2. 문장 속 목록 둘" in by["r3-1"].text
    # 마침표 없이 끝난 마지막 줄에 직인 번호·심판관 서명·[별지]가 이어 붙지 않는다
    assert by["r4-0"].text == "4. 결론\n지어낸 결론 글이다 마침표 없이 끝나는 줄"
    assert all(not re.search(r"별지|심판장|심판관|【청구항|^\d{8}$", c.text) for c in chunks)
    # 판단 아래 "1) 청구인의 주장"은 court 조각에 섞이지 않는다
    assert by["r3-1-1"].speaker == "party"
    assert by["r3-1-2"].speaker == "court"


def test_심결_조각_메타와_발언_주체():
    chunks = chunk_trial(_trial_pages(), TRIAL_FILE, V, trial_type="진보성만")
    by = _by_id(chunks)
    for c in chunks:
        assert c.doc_id == "심결_2099원1234"
        assert c.chunk_id.startswith("law-idx-v3:심결_2099원1234:r")
        assert c.chunk_kind == "judgment"
        assert c.source_kind == "trial"
        assert c.edition.status == "not_applicable"
        assert c.decided_on == date(2099, 10, 1)
        assert c.attrs == {"결과": "원결정 취소", "유형": "진보성만"}
        assert (
            check_law_chunk(c.chunk_kind, c.edition.status, c.source_kind, c.decided_on, c.speaker)
            is None
        )
    assert by["r1-1"].speaker == "unknown"  # 기초사실
    assert by["r2-0"].speaker == "party"  # 청구인의 주장
    assert by["r3-1"].speaker == "court"  # 판단 (심판부)
    assert by["r4-0"].speaker == "court"  # 결론


def test_심결일_못_뽑으면_null과_경고(caplog):
    pages = [p.replace("심    결   일   2099. 10. 1.", "") for p in _trial_pages()]
    with caplog.at_level(logging.WARNING):
        chunks = chunk_trial(pages, TRIAL_FILE, V)
    assert {c.decided_on for c in chunks} == {None}
    assert "심결_2099원1234" in caplog.text


def test_결과는_주문에서_기각도_읽음():
    pages = [
        p.replace(
            "원결정을 취소하고, 이 사건 출원을 심사관에게 보내어 다시 심사에 부친다.",
            "이 사건 심판청구를 기각한다.",
        )
        for p in _trial_pages()
    ]
    assert chunk_trial(pages, TRIAL_FILE, V)[0].attrs["결과"] == "기각"


def test_심결_이유_제목_없으면_오류():
    pages = [p.replace("이          유", "") for p in _trial_pages()]
    with pytest.raises(PrecedentIndexError, match="이 유"):
        chunk_trial(pages, TRIAL_FILE, V)


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


def test_문장_속_번호가_먼저_나와도_진짜_제목을_삼키지_않음():
    lines = [
        "1. 경위",
        "지어낸 경위 글이다.",
        "2. 청구인이 낸 첫째 서류 이름",  # 문장 속 목록인데 번호가 맞아 제목으로 받아짐
        "지어낸 서류 글이다.",
        "2. 판단",  # 같은 번호의 진짜 제목: 다시 맞춘다
        "지어낸 판단 글이다.",
        "4. 결론",  # 건너뛴 번호도 짧은 제목 꼴이면 받는다
        "지어낸 결론 글이다.",
    ]
    parts = split_numbered(lines)
    assert [p.key for p in parts] == ["r1-0", "r2-0", "r2-0-d1", "r4-0"]
    assert [p.heads[-1] for p in parts][2] == "2. 판단"
    assert _speaker_of(parts[2]) == "court"
    # 긴 줄은 기대 번호일 때만 번호로 본다
    long_line = "3. " + "지어낸 아주 긴 문장입니다 " * 8
    parts2 = split_numbered(["1. 경위", "글", long_line])
    assert [p.key for p in parts2] == ["r1-0"]


def _speaker_of(part):
    from patent_ai.retrieval.precedent_index import _speaker

    return _speaker(part.heads)


def test_긴_조각은_문단_경계에서_나누고_한_문단이_길면_문장_끝에서():
    assert pack_lines(["가나다", "라마바"], max_chars=100) == [["가나다", "라마바"]]
    assert pack_lines(["a" * 40, "b" * 40, "c" * 40], max_chars=90) == [
        ["a" * 40, "b" * 40],
        ["c" * 40],
    ]
    # 한 줄이 상한보다 길면 문장 끝(.)에서
    sentence = "가" * 30 + "."
    groups = pack_lines([" ".join([sentence] * 4)], max_chars=70)
    assert groups == [[f"{sentence} {sentence}"], [f"{sentence} {sentence}"]]


def test_max_chars를_넘는_조각은_p키와_n_m_label로_나뉨():
    data = _load("patent_court.json")
    chunks = chunk_precedent(data, V, max_chars=30)
    split = [c for c in chunks if "-p" in c.chunk_id]
    assert split, "30자 상한이면 나뉘는 조각이 있어야 한다"
    assert max(len(c.text) for c in chunks) <= 30
    first = next(c for c in split if c.chunk_id.endswith("-p1"))
    assert re.search(r"\(1/\d+\)$", first.location.label)
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    # 상한 없으면 그대로
    assert all("-p" not in c.chunk_id for c in chunk_precedent(data, V))


def test_심결_별지_제목이_없는데_청구항이_이유_뒤에_있으면_경고(caplog):
    pages = [p.replace("별지 1]", "") for p in _trial_pages()]
    with caplog.at_level(logging.WARNING):
        chunks = chunk_trial(pages, TRIAL_FILE, V)
    assert "【청구항" in caplog.text
    assert all("청구항" not in c.text for c in chunks)  # 서명 뒤는 버린다


def test_대법원장_서명_줄도_뺌():
    data = _load("supreme_no_summary.json")
    data["PrecService"]["판례내용"] = data["PrecService"]["판례내용"].replace(
        "대법관 가상삼(재판장) 가상사", "대법원장 가상오"
    )
    chunks = chunk_precedent(data, V)
    assert all("대법원장" not in c.text for c in chunks)
