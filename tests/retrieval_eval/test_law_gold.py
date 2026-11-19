"""법령 정답 변환 테스트 (#66 task 2). 검수한 검색 정답 json + OA 글 → 법령 정답 줄."""

import json
from datetime import date

import pytest

from eval.retrieval.checks import find_leaks
from eval.retrieval.gold import load_gold
from eval.retrieval.law_gold import (
    LawGoldError,
    convert,
    edition_for,
    mask_articles,
    parse_articles,
    segment_reasons,
    write_gold,
)

OA = """[심사결과]
□ 이 출원의 거절이유가 있는 부분과 관련 법조항
    1    청구항 제13항                 특허법 제29조제1항제2호
[구체적인 거절이유]
머리말 줄은 버린다.
1. 이 출원의 청구범위의 청구항 제13항에 기재된 발명은 간행물에 게재된 발명이므로
특허법 제29조제1항제2호에 해당하여 특허를 받을 수 없습니다.
  1   표 안의 번호 줄은 제목이 아니다
2. 이 출원의 청구항 제1항 발명은 통상의 기술자가 쉽게 발명할 수 있으므로
특허법 제29조 제2항에 따라 특허를 받을 수 없습니다. (29조 2항)
3. 이 출원은 청구항 제12항의 기재가 불비하여 특허법 제42조제4항제2호 및
같은 법 시행령 제5조제6항에 따른 요건을 충족하지 못합니다.
[첨 부]
1. 특허법 제47조제2항에 따라 보정할 수 있습니다.
"""


# --- 거절이유 자르기 ---


def test_구체적인_거절이유를_순번별로_자른다():
    segs = segment_reasons(OA)
    assert list(segs) == [1, 2, 3]
    assert segs[1].startswith("1. 이 출원의 청구범위의 청구항 제13항")
    assert "표 안의 번호 줄은 제목이 아니다" in segs[1]  # 들여쓴 번호 줄은 제목이 아님
    assert "머리말" not in segs[1]
    assert "보정할 수 있습니다" not in segs[3]  # [첨 부] 뒤는 버린다


def test_순번_제목이_없으면_본문_전체가_1번():
    text = "[구체적인 거절이유]\n청구항 1 발명은 쉽게 발명할 수 있습니다.\n[첨 부]\n안내"
    assert segment_reasons(text) == {1: "청구항 1 발명은 쉽게 발명할 수 있습니다."}


def test_안내_표시에서도_본문이_끝난다():
    # 실제 OA 두 건은 [첨 부] 대신 "<< 안내 >>" 뒤에 번호 붙은 안내문이 온다
    text = (
        "[구체적인 거절이유]\n청구항 1의 기재가 불비합니다.\n"
        "                        << 안내 >>\n1. 지정기간연장 안내\n2. 보정료 안내"
    )
    assert segment_reasons(text) == {1: "청구항 1의 기재가 불비합니다."}


def test_심사관_서명_줄에서_본문이_끝나_이름이_안_들어간다():
    text = (
        "[구체적인 거절이유]\n청구항 1의 기재가 불비합니다.\n\n"
        "  전기통신기술심사국\n"
        "     방송미디어심사팀               심사관 홍길동\n"
        "  융복합기술심사국 인공지능심사과     심사관 김철수\n"
        "                        << 안내 >>\n1. 안내"
    )
    assert segment_reasons(text) == {1: "청구항 1의 기재가 불비합니다."}


def test_본문_표시가_없으면_멈춘다():
    with pytest.raises(LawGoldError):
        segment_reasons("아무 표시 없는 글")


# --- 조문 가리기 ---


def test_조문_표기는_가리고_청구항_번호는_둔다():
    t = mask_articles(
        "청구항 제13항은 특허법 제29조제1항제2호, 특허법 제29조 제2항, 29조 2항, "
        "같은 법 시행령 제5조제6항, 제7조의2에 해당"
    )
    assert "조" not in t.replace("[조문]", "")
    assert "청구항 제13항" in t
    assert t.count("[조문]") == 5


# --- 조문 문자열 → 정답 항목 ---


def test_조문_문자열을_법령과_6자리_위치로():
    assert parse_articles("특허법 제29조제1항제2호") == [
        ("특허법", 290001, "특허법 제29조제1항제2호")
    ]
    assert parse_articles("특허법 제42조제8항, 특허법 시행령 제5조제6항") == [
        ("특허법", 420008, "특허법 제42조제8항"),
        ("특허법_시행령", 50006, "특허법 시행령 제5조제6항"),
    ]
    assert parse_articles("특허법 제7조의2") == [("특허법", 70200, "특허법 제7조의2")]
    with pytest.raises(LawGoldError):
        parse_articles("심사기준 제3부")


def test_적용판본_문자열에서_법령별_판본():
    applied = {
        "특허법": "특허법_212229_20200311 (+시행령_193953_20170603, 5조⑥ 문구는 같음)",
        "심사기준": "심사기준_예규113_20200101",
    }
    ed = edition_for(applied, "특허법")
    assert ed.status == "confirmed"
    assert ed.effective_from == date(2020, 3, 11)
    assert ed.label == "특허법_212229_20200311"
    ed2 = edition_for(applied, "특허법_시행령")
    assert ed2.effective_from == date(2017, 6, 3)
    assert ed2.label == "특허법_시행령_193953_20170603"


def test_판본을_못_찾으면_unverified():
    ed = edition_for({"특허법": "모름"}, "특허법")
    assert ed.status == "unverified" and ed.effective_from is None
    assert edition_for({"특허법": "특허법_212229_20200311"}, "특허법_시행령").status == "unverified"


# --- 사건 → 정답 줄 ---


def _case(applied=None, oa_no="9520"):
    return {
        "출원번호": "1020",
        "발송번호": oa_no,
        "발송일": "2020-04-16",
        "적용판본": applied or {"특허법": "특허법_212229_20200311 (+시행령_193953_20170603)"},
        "거절이유": [
            {"순번": 1, "조문": "특허법 제29조제1항제2호"},
            {"순번": 2, "조문": "특허법 제29조제2항"},
            {"순번": 3, "조문": "특허법 제42조제4항제2호, 특허법 시행령 제5조제6항"},
        ],
    }


def _oa_dir(tmp_path, name="1020_OA_9520.txt", text=OA):
    d = tmp_path / "oa"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d


def test_사건을_정답_줄로(tmp_path):
    rows, skipped = convert([_case()], _oa_dir(tmp_path))
    assert skipped == 0
    assert [r.row_id for r in rows] == ["9520:r1", "9520:r2", "9520:r3"]
    r3 = rows[2]
    assert r3.corpus == "law" and r3.doc_ids is None and r3.exclude is None
    assert r3.as_of == date(2020, 4, 16)
    assert [(i.kind, i.start, i.end) for i in r3.items] == [
        ("article", 420004, 420004),
        ("article", 50006, 50006),
    ]
    assert r3.items[1].gold_edition.effective_from == date(2017, 6, 3)
    # 가린 질의는 채점기 누설 검사를 통과한다
    assert all(find_leaks(r) == [] for r in rows)
    assert "[조문]" in rows[1].query and "쉽게 발명할 수" in rows[1].query


def test_판본_모르는_항목이_있으면_줄은_남기고_채점기가_뺀다(tmp_path):
    rows, _ = convert([_case(applied={"특허법": "특허법_212229_20200311"})], _oa_dir(tmp_path))
    # 시행령 판본이 없다: 줄은 쓰되 edition_confirmed()가 False라 채점기가 분모에서 뺀다
    assert rows[0].edition_confirmed() and not rows[2].edition_confirmed()


def test_자르기가_정답_순번과_안_맞으면_그_사건은_빼고_센다(tmp_path, caplog):
    two = OA.replace("3. 이 출원은", "이 출원은")  # 순번이 2까지만
    rows, skipped = convert([_case()], _oa_dir(tmp_path, text=two))
    assert rows == [] and skipped == 3
    assert "9520" in caplog.text


def test_OA_파일이_없으면_빼고_센다(tmp_path, caplog):
    rows, skipped = convert([_case(oa_no="0000")], _oa_dir(tmp_path))
    assert rows == [] and skipped == 3
    assert "0000" in caplog.text


def test_줄이_0개면_쓰지_않고_멈춘다(tmp_path):
    out = tmp_path / "law_gold.jsonl"
    with pytest.raises(LawGoldError):
        write_gold([], out)
    assert not out.exists()


def test_쓴_파일을_채점기가_읽고_덮어쓰지_않는다(tmp_path):
    rows, _ = convert([_case()], _oa_dir(tmp_path))
    out = tmp_path / "retrieval" / "law_gold.jsonl"
    write_gold(rows, out)
    assert [r.row_id for r in load_gold(out)] == ["9520:r1", "9520:r2", "9520:r3"]
    with pytest.raises(LawGoldError):
        write_gold(rows, out)
    # 질의 원문이 다른 칸에 새지 않는다: 한 줄 = JSON 하나
    assert all(json.loads(line)["corpus"] == "law" for line in out.read_text().splitlines())
