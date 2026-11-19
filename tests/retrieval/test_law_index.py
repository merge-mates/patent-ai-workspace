"""법령 청커 테스트 (#66 task 1). 입력은 법제처 본문 JSON 모양을 줄여 손으로 만든 것."""

import json
from datetime import date

import pytest

from patent_ai.retrieval.law_index import (
    LawIndexError,
    article_loc,
    build_index,
    chunk_law,
    editions_for,
    parse_raw_name,
    write_jsonl,
)
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Edition

V = "law-idx-v1"
ED = Edition(status="confirmed", effective_from=date(2020, 3, 11), label="특허법_212229_20200311")


def _law(시행일: str, 조문: list[dict], 이름: str = "특허법") -> dict:
    return {
        "법령": {"기본정보": {"법령명_한글": 이름, "시행일자": 시행일}, "조문": {"조문단위": 조문}}
    }


# 제29조: 항 ①(호 2개), ② / 장 제목(전문) / 제2조: 항번호 없이 호만 / 제7조의2: 가지조문
조29 = {
    "조문번호": "29",
    "조문여부": "조문",
    "조문내용": "제29조(특허요건)",
    "항": [
        {
            "항번호": "①",
            "항내용": "① 산업상 이용할 수 있는 발명은 특허를 받을 수 있다. <개정 2016.2.29>",
            "호": [
                {"호번호": "1.", "호내용": "1. 공지된 발명"},
                {"호번호": "2.", "호내용": "2. 간행물에 게재된 발명"},
            ],
        },
        {"항번호": "②", "항내용": "② 쉽게 발명할 수 있으면 특허를 받을 수 없다."},
        {"항번호": "③", "항내용": "③ 삭제 <2016.2.29>"},
    ],
}
장제목 = {"조문번호": "29", "조문여부": "전문", "조문내용": "  제2장 특허요건 <개정 2014.6.11>"}
조2 = {
    "조문번호": "2",
    "조문여부": "조문",
    "조문내용": "제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.",
    "항": {
        "호": [
            {
                "호번호": "3.",
                "호내용": '3. "실시"란 다음 각 목의 행위를 말한다.',
                "목": [{"목번호": "가.", "목내용": "가. 생산하는 행위"}],
            }
        ]
    },
}
조7의2 = {
    "조문번호": "7",
    "조문가지번호": "2",
    "조문여부": "조문",
    "조문내용": "제7조의2(추인) 흠이 있는 자가 한 절차는 추인할 수 있다.",
}
조26삭제 = {"조문번호": "26", "조문여부": "조문", "조문내용": "제26조 삭제 <2011.12.2>"}


def _by_label(chunks):
    return {c.location.label: c for c in chunks}


# --- 위치 번호·파일 이름 ---


def test_위치번호는_조_가지_항_6자리():
    assert article_loc(29, 0, 2) == 290002
    assert article_loc(52, 2, 1) == 520201
    assert article_loc(2, 0, 0) == 20000


def test_파일이름에서_법령이름과_doc_id():
    assert parse_raw_name("body_특허법_212229_20200311.json") == (
        "특허법",
        "특허법_212229_20200311",
    )
    assert parse_raw_name("body_특허법_시행령_233263_20210623.json") == (
        "특허법_시행령",
        "특허법_시행령_233263_20210623",
    )
    with pytest.raises(LawIndexError):
        parse_raw_name("notes.json")


# --- 조각 자르기 ---


def test_항_단위로_자르고_호는_그_항_안에():
    chunks = chunk_law(_law("20200311", [조29]), "특허법_212229_20200311", ED, V)
    got = _by_label(chunks)
    assert set(got) == {"제29조제1항", "제29조제2항"}  # 삭제된 ③은 빠짐
    p1 = got["제29조제1항"]
    assert p1.location.kind == "article"
    assert p1.location.start == p1.location.end == 290001
    assert p1.chunk_kind == "article"
    assert p1.chunk_id == "law-idx-v1:특허법_212229_20200311:290001"
    # 조 제목이 앞에 붙고, 호 글이 같이 들어가고, 개정 꼬리표는 지워진다
    assert p1.text.startswith("제29조(특허요건) ① 산업상")
    assert "1. 공지된 발명" in p1.text and "2. 간행물에 게재된 발명" in p1.text
    assert "<개정" not in p1.text
    assert (
        got["제29조제2항"].text == "제29조(특허요건) ② 쉽게 발명할 수 있으면 특허를 받을 수 없다."
    )


def test_장_제목과_삭제된_조는_조각이_안_된다():
    chunks = chunk_law(_law("20200311", [장제목, 조26삭제, 조29]), "d", ED, V)
    assert all(c.location.start // 10000 == 29 for c in chunks)


def test_항번호_없이_호만_있으면_조_하나가_항0_조각():
    (c,) = chunk_law(_law("20200311", [조2]), "d", ED, V)
    assert c.location.start == 20000
    assert c.location.label == "제2조"
    assert c.text.startswith("제2조(정의) 이 법에서")
    assert '3. "실시"란' in c.text and "가. 생산하는 행위" in c.text


def test_목내용이_겹목록이어도_글을_다_넣는다():
    # 실제 시행령 제7조: 목내용이 [["어. …", "1) …", "2) …"]] 모양
    art = {
        "조문번호": "7",
        "조문여부": "조문",
        "조문내용": "제7조(기간)",
        "항": [
            {
                "항번호": "①",
                "항내용": "① 기간은 다음과 같다.",
                "호": {
                    "호번호": "1.",
                    "호내용": "1. 다음 각 목의 기간",
                    "목": {"목번호": "어.", "목내용": [["어. 서류 제출 기간", "  1) 미생물 서류"]]},
                },
            }
        ],
    }
    (c,) = chunk_law(_law("20210623", [art]), "d", ED, V)
    assert c.text == (
        "제7조(기간) ① 기간은 다음과 같다. 1. 다음 각 목의 기간 어. 서류 제출 기간 1) 미생물 서류"
    )


def test_가지조문은_가지_자리에():
    (c,) = chunk_law(_law("20200311", [조7의2]), "d", ED, V)
    assert c.location.start == 70200
    assert c.location.label == "제7조의2"


def test_조각마다_판본이_붙는다():
    chunks = chunk_law(_law("20200311", [조29, 조2]), "d", ED, V)
    assert chunks and all(c.edition == ED for c in chunks)


# --- 판본 ---


def test_판본은_시행일_순으로_끝일은_다음판_전날():
    # 번호(MST)는 222497이 더 크지만 시행일은 더 이르다: 번호 순이 아니라 시행일 순
    files = {
        "특허법_219103_20201210": "20201210",
        "특허법_222497_20201020": "20201020",
        "특허법_212229_20200311": "20200311",
    }
    eds = editions_for(files)
    assert eds["특허법_212229_20200311"].effective_to == date(2020, 10, 19)
    assert eds["특허법_222497_20201020"].effective_to == date(2020, 12, 9)
    last = eds["특허법_219103_20201210"]
    assert last.status == "confirmed"
    assert last.effective_from == date(2020, 12, 10)
    assert last.effective_to is None  # 마지막 판은 지금도 효력
    assert last.label == "특허법_219103_20201210"


def test_시행일을_못_읽으면_unverified():
    eds = editions_for(
        {"특허법_1_20200311": "20200311", "특허법_2_x": "", "특허법_3_y": "2020-13-40"}
    )
    assert eds["특허법_2_x"].status == "unverified"
    assert eds["특허법_2_x"].effective_from is None
    assert eds["특허법_3_y"].status == "unverified"
    # 시행일을 아는 판은 그대로 (모르는 판은 줄 세우기에서 빠짐)
    assert eds["특허법_1_20200311"].effective_to is None


def test_같은_법_같은_시행일이_둘이면_멈춘다():
    with pytest.raises(LawIndexError):
        editions_for({"특허법_1_20200311": "20200311", "특허법_2_20200311": "20200311"})


# --- 색인 전체 ---


def _raw_dir(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    files = {
        "body_특허법_212229_20200311.json": _law("20200311", [조29]),
        "body_특허법_222497_20201020.json": _law("20201020", [조29, 조2]),
        "body_특허법_시행령_233263_20210623.json": _law("20210623", [조7의2], "특허법 시행령"),
        "body_특허법_시행규칙_236447_20211021.json": _law("20211021", [조2], "특허법 시행규칙"),
    }
    for name, data in files.items():
        (raw / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return raw


LAWS = ["특허법", "특허법_시행령"]


def test_설정한_법령만_읽고_뺀_파일은_센다(tmp_path):
    chunks, skipped = build_index(_raw_dir(tmp_path), LAWS, V)
    assert skipped == 1  # 시행규칙
    assert {c.doc_id for c in chunks} == {
        "특허법_212229_20200311",
        "특허법_222497_20201020",
        "특허법_시행령_233263_20210623",
    }
    # 법마다 따로 줄 세운다: 시행령 하나뿐이라 끝일 없음
    old = next(c for c in chunks if c.doc_id == "특허법_212229_20200311")
    assert old.edition.effective_to == date(2020, 10, 19)


def test_같은_입력이면_두_번_만들어도_같은_바이트(tmp_path):
    raw = _raw_dir(tmp_path)
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl(build_index(raw, LAWS, V)[0], a)
    write_jsonl(build_index(raw, LAWS, V)[0], b)
    assert a.read_bytes() == b.read_bytes()
    # 저장소가 그대로 읽는다 (chunk_id 겹침·판본 상태 검사 통과)
    repo = InMemoryChunkRepository.from_jsonl("law", a)
    assert repo.count_chunks("law", V) == 6


def test_이미_있는_파일은_덮어쓰지_않는다(tmp_path):
    out = tmp_path / "x.jsonl"
    out.write_text("old", encoding="utf-8")
    with pytest.raises(LawIndexError):
        write_jsonl(build_index(_raw_dir(tmp_path), LAWS, V)[0], out)
    assert out.read_text(encoding="utf-8") == "old"


def test_조각이_0개면_경고하고_멈춘다(tmp_path, caplog):
    with pytest.raises(LawIndexError):
        build_index(_raw_dir(tmp_path), ["없는법"], V)
    assert "0개" in caplog.text
