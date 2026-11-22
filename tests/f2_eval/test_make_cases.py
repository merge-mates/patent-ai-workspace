"""F2 정답 만들기 (eval/f2/make_cases.py). 법령·판례·정답 줄은 모두 지어낸 값이다."""

import json
import logging
from datetime import date

import pytest

from eval.f2.gold import ERROR_KINDS, InjectedCase, RealCase, count_cases, load_f2_cases
from eval.f2.make_cases import main

D1, D2, D3 = "특허법_100001_20150101", "특허법_100002_20180101", "특허법_100003_20210101"
CHECKED_ON = "2022-06-01"  # 이날 시행 중인 판 = D3


def _art(jo, gaji, title, hangs=None, body=""):
    """법제처 JSON 조문단위 하나. hangs가 없으면 항 없는 조(조 글에 본문)."""
    head = f"제{jo}조" + (f"의{gaji}" if gaji else "") + f"({title})"
    art = {
        "조문여부": "조문",
        "조문번호": str(jo),
        "조문가지번호": str(gaji) if gaji else "",
        "조문내용": head + (f" {body}" if body else ""),
    }
    if hangs:
        art["항"] = [
            {"항번호": chr(ord("①") + i), "항내용": f"{chr(ord('①') + i)} {t}"}
            for i, t in enumerate(hangs)
        ]
    return art


def _law(date_str, p52, p53, p672, p13217):
    arts = [
        _art(28, 0, "가짜제목28", ["가짜 글 스물여덟"]),
        _art(29, 0, "가짜제목29", ["가짜 글 하나", "가짜 글 둘"]),
        _art(29, 2, "가짜제목29의2", ["가짜 글 의이"]),
        _art(30, 0, "가짜제목30", ["가짜 글 서른"]),
        _art(52, 0, "가짜제목52", [f"기한은 {p52} 이내"]),
        _art(53, 0, "가짜제목53", [f"기한은 {p53} 이내"]),
        _art(67, 2, "가짜제목67의2", [f"기한은 {p672} 이내"]),
        _art(132, 17, "가짜제목132의17", body=f"기한은 {p13217} 이내"),
    ]
    return {"법령": {"기본정보": {"시행일자": date_str}, "조문": {"조문단위": arts}}}


LAWS = {
    D1: _law("20150101", "30일", "10일", "1년", "6개월"),
    D2: _law("20180101", "2개월", "3개월", "1년", "6개월"),
    D3: _law("20210101", "3개월", "3개월", "2년", "3개월"),
}


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _row(row_id, doc_id, start, label, status="confirmed", as_of="2019-05-05"):
    ed = {"status": status, "label": doc_id}
    if status == "confirmed":
        ed |= {"effective_from": "2015-01-01"}
    return {
        "row_id": row_id,
        "corpus": "law",
        "query": f"가짜 질의 {row_id}",
        "as_of": as_of,
        "items": [
            {"kind": "article", "start": start, "end": start, "label": label, "gold_edition": ed}
        ],
    }


ROWS = [
    _row("o1:r1", D2, 290002, "특허법 제29조제2항"),
    _row("o2:r2", D1, 290001, "특허법 제29조제1항", as_of="2016-05-05"),
    _row("o3:r1", D3, 290002, "특허법 제29조제2항", as_of="2022-01-05"),
    _row("o4:r1", D2, 520001, "특허법 제52조제1항"),
    _row("o5:r1", D2, 290002, "특허법 제29조제2항", status="unverified"),  # 뺀다
    _row("o6:r1", D1, 290002, "특허법 제29조제2항"),  # 정답 판 D1이 발송일(2019)을 안 품음: 뺀다
]

PRECS = [  # (사건번호, 일련번호, 판결요지)
    ("2001후100", "1", "가짜 요지 <br/> 첫째"),
    ("2002후200", "2", "<br/>"),  # 태그 지우면 빔: 뺀다
    ("2003후300", "3", "가짜 요지 셋"),
    ("2004후400", "4", "가짜 요지 넷"),
    ("2005후500", "5", "가짜 요지 다섯"),
    ("2006후600", "6", "가짜 요지 여섯"),
]


def _prec(no, serial, summary):
    return {
        "PrecService": {
            "사건번호": no,
            "판결요지": summary,
            "판례내용": "가짜 전문",
            "선고일자": "20100203",
            "법원명": "가짜법원",
            "판례정보일련번호": serial,
        }
    }


class Mats:
    """재료 폴더 한 벌."""

    def __init__(self, tmp_path):
        self.law_raw, self.prec_raw = tmp_path / "law", tmp_path / "prec"
        self.roots = tmp_path / "goldsets"
        for d in (self.law_raw, self.prec_raw, self.roots):
            d.mkdir()
        (self.roots / "VERSION").write_text("2\n")
        for doc_id, data in LAWS.items():
            _write_json(self.law_raw / f"body_{doc_id}.json", data)
        for no, serial, summary in PRECS:
            _write_json(self.prec_raw / f"body_{no}_{serial}.json", _prec(no, serial, summary))
        self.gold = tmp_path / "law_gold.jsonl"
        self.gold.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS) + "\n", encoding="utf-8"
        )
        self.out = tmp_path / "o.jsonl"

    def args(self):
        return [
            "--law-gold", str(self.gold),
            "--law-raw", str(self.law_raw),
            "--prec-raw", str(self.prec_raw),
            "--goldsets-root", str(self.roots),
            "--checked-on", CHECKED_ON,
            "--out", str(self.out),
        ]  # fmt: skip


@pytest.fixture
def mats(tmp_path):
    return Mats(tmp_path)


def _run(m):
    assert main(m.args()) == 0
    return load_f2_cases(m.out, 2)


def _inj(cases, error):
    return sorted(
        (c for c in cases if isinstance(c, InjectedCase) and c.error == error),
        key=lambda c: c.case_id,
    )


def test_make_cases_종류마다_4개이고_load를_통과한다(mats):
    cases = _run(mats)
    counts = count_cases(cases)
    assert counts["real"] == 4  # unverified 줄 하나는 뺐다
    assert all(counts[e] == 4 for e in ERROR_KINDS)
    assert counts["total"] == 24
    assert [c.case_id for c in cases] == sorted(c.case_id for c in cases)


def test_make_cases_실제_질문_모양(mats):
    cases = _run(mats)
    r = next(c for c in cases if c.case_id == "real:o2:r2")
    assert isinstance(r, RealCase)
    assert (r.oa_id, r.rejection) == ("o2", 2)
    assert r.question.text == "가짜 질의 o2:r2"
    assert r.question.as_of == date(2016, 5, 5)
    assert r.question.article_refs == ["특허법 제29조제1항"]
    es = r.expect_sources[0]
    assert (es.identifier, es.document_id, es.loc) == ("특허법 제29조제1항", D1, 290001)


def test_make_cases_같은_입력이면_같은_바이트(mats, tmp_path):
    assert main(mats.args()) == 0
    first = mats.out.read_bytes()
    args = mats.args()
    other = tmp_path / "again.jsonl"
    args[args.index("--out") + 1] = str(other)
    assert main(args) == 0
    assert other.read_bytes() == first


def test_make_cases_있는_파일은_덮지_않는다(mats):
    mats.out.write_text("keep", encoding="utf-8")
    assert main(mats.args()) == 1
    assert mats.out.read_text(encoding="utf-8") == "keep"


def test_make_cases_판례가_모자라면_멈춘다(mats):
    for p in sorted(mats.prec_raw.glob("body_*.json"))[3:]:
        p.unlink()  # 3개만 남김
    assert main(mats.args()) == 1
    assert not mats.out.exists()


def test_make_cases_실제_질문이_4개_미만이면_멈춘다(mats):
    lines = mats.gold.read_text(encoding="utf-8").splitlines()[1:]
    mats.gold.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(mats.args()) == 1
    assert not mats.out.exists()


def test_make_cases_정답_조각이_원문에_없으면_멈춘다(mats):
    rows = [json.loads(x) for x in mats.gold.read_text(encoding="utf-8").splitlines()]
    rows[0]["items"][0]["start"] = 990001  # 원문에 없는 위치
    mats.gold.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    assert main(mats.args()) == 1
    assert not mats.out.exists()


def test_make_cases_뺀_줄은_경고한다(mats, caplog):
    with caplog.at_level(logging.WARNING):
        main(mats.args())
    assert any("o5:r1" in r.getMessage() for r in caplog.records)


def test_make_cases_정답_판이_발송일을_안_품으면_경고하고_뺀다(mats, caplog):
    with caplog.at_level(logging.WARNING):
        cases = _run(mats)
    assert "real:o6:r1" not in {c.case_id for c in cases}
    assert any("o6:r1" in r.getMessage() and "발송일" in r.getMessage() for r in caplog.records)


def test_make_cases_판례를_뺀_수를_경고한다(mats, caplog):
    with caplog.at_level(logging.WARNING):
        _run(mats)
    # 2002후200은 태그를 지우면 요지가 빈다
    assert any("판례 원문 1개" in r.getMessage() for r in caplog.records)


def test_make_cases_주입_묶음은_F2_모양이다(mats):
    cases = _run(mats)
    inj = _inj(cases, "other_edition_asserted")[0]
    assert inj.case_id == "inject:other_edition_asserted:1"
    assert inj.base_case_id == "real:o1:r1"
    b = inj.bundle
    assert b.bundle_id == "lb:inject:other_edition_asserted:1"
    assert (b.oa_id, b.rejection, b.unit_id) == ("o1", 1, None)
    assert b.checked_on == date(2022, 6, 1)
    assert b.status.value == "confirmed"
    claim = b.claims[0]
    assert claim.text == "거절이유 근거 조문: 특허법 제29조제2항 (OA 발송일 2019-05-05 시행판)"
    assert claim.review is None and [f.value for f in claim.flags] == ["needs_human_review"]
    assert inj.reviewed.by is None and inj.reviewed.date is None


def test_make_cases_없는_출처는_없는_가지_번호를_고른다(mats):
    cases = _run(mats)
    by_base = {c.base_case_id: c for c in _inj(cases, "nonexistent_source")}
    # 바탕 o1(29조2항, D2): 29조의2는 있어 g=3, 같은 2항
    s = by_base["real:o1:r1"].bundle.claims[0].sources[0]
    assert s.identifier == "특허법 제29조의3제2항"
    assert s.evidence.location == "제29조의3제2항"
    assert s.evidence.chunk_id == f"law-idx-v2:{D2}:290302"
    assert s.evidence.raw_text == "제29조(가짜제목29) ② 가짜 글 둘"  # 바탕 글 그대로
    # 바탕 o2(29조1항): 같은 방식, 항은 1
    assert by_base["real:o2:r2"].bundle.claims[0].sources[0].identifier == "특허법 제29조의3제1항"
    # 52조에는 가지가 없으니 g=2
    assert by_base["real:o4:r1"].bundle.claims[0].sources[0].identifier == "특허법 제52조의2제1항"
    assert all(c.fix is None for c in by_base.values())
    assert all(c.target_claim == 1 and c.target_source == 0 for c in by_base.values())


def test_make_cases_없는_출처는_지워진_가지_조문도_건너뛴다(mats):
    # 옛 판 D1에 "제29조의3 삭제"가 있으면 29조의3은 있던 번호다 → 29조의4를 고른다
    data = _law("20150101", "30일", "10일", "1년", "6개월")
    deleted = {
        "조문여부": "조문",
        "조문번호": "29",
        "조문가지번호": "3",
        "조문내용": "제29조의3 삭제",
    }
    data["법령"]["조문"]["조문단위"].append(deleted)
    _write_json(mats.law_raw / f"body_{D1}.json", data)
    cases = _run(mats)
    by_base = {c.base_case_id: c for c in _inj(cases, "nonexistent_source")}
    assert by_base["real:o1:r1"].bundle.claims[0].sources[0].identifier == "특허법 제29조의4제2항"


def test_make_cases_없는_출처는_다른_판에만_있는_가지도_건너뛴다(mats):
    # 현행 판 D3에만 52조의2가 생겼다 → 바탕 판(52조 바탕)에 없어도 "없는 출처"로 쓰면 안 된다
    data = _law("20210101", "3개월", "3개월", "2년", "3개월")
    data["법령"]["조문"]["조문단위"].append(_art(52, 2, "가짜제목52의2", ["가짜 글 오십이의이"]))
    _write_json(mats.law_raw / f"body_{D3}.json", data)
    cases = _run(mats)
    by_base = {c.base_case_id: c for c in _inj(cases, "nonexistent_source")}
    assert by_base["real:o4:r1"].bundle.claims[0].sources[0].identifier == "특허법 제52조의3제1항"


def test_make_cases_주장_불일치는_다음_제목_있는_조문(mats):
    cases = _run(mats)
    c = _inj(cases, "claim_text_mismatch")[0]  # 바탕 o1
    claim = c.bundle.claims[0]
    assert claim.text == "특허법 제29조제2항은(는) 가짜제목29의2에 관하여 정한다."
    assert claim.sources[0].identifier == "특허법 제29조제2항"
    assert c.fix is None


def test_make_cases_다른_판본은_가장_늦은_다른_판(mats):
    cases = _run(mats)
    c = {x.base_case_id: x for x in _inj(cases, "other_edition_asserted")}
    # o1: 정답 D2, 같은 loc가 있는 다른 판 중 가장 늦은 D3
    s = c["real:o1:r1"].bundle.claims[0].sources[0]
    assert s.evidence.document_id == D3
    assert s.evidence.edition == f"{D3} 시행 2021-01-01 ~ 현행"
    assert c["real:o1:r1"].fix.document_id == D2
    # o3: 정답이 D3(가장 늦은 판)이면 가장 이른 다른 판 D1
    assert c["real:o3:r1"].bundle.claims[0].sources[0].evidence.document_id == D1
    assert c["real:o3:r1"].fix.document_id == D3


def test_make_cases_다른_판본은_기준일에_시행_중인_판을_고르지_않는다(mats):
    # 정답 판이 기준일을 안 품는 줄(o6)은 빠지고, 남은 줄의 주입 판은 모두 기준일 밖이어야 한다
    cases = _run(mats)
    by_id = {c.case_id: c for c in cases if isinstance(c, RealCase)}
    for c in _inj(cases, "other_edition_asserted"):
        doc = c.bundle.claims[0].sources[0].evidence.document_id
        as_of = by_id[c.base_case_id].question.as_of
        assert doc != c.fix.document_id
        # 고른 판은 기준일 밖, 고칠 정답 판은 기준일 안
        ed_from = {D1: date(2015, 1, 1), D2: date(2018, 1, 1), D3: date(2021, 1, 1)}
        ed_to = {D1: date(2017, 12, 31), D2: date(2020, 12, 31), D3: None}
        assert not (ed_from[doc] <= as_of and (ed_to[doc] is None or as_of <= ed_to[doc]))


def test_make_cases_주입_종류마다_바탕_질문이_겹치지_않는다(mats):
    # 실제 질문이 넉넉하면(12개 이상) 없는 출처·불일치·다른 판이 서로 다른 바탕을 쓴다
    rows = [json.loads(x) for x in mats.gold.read_text(encoding="utf-8").splitlines()]
    rows += [_row(f"p{i:02d}:r1", D2, 290002, "특허법 제29조제2항") for i in range(10)]
    mats.gold.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    cases = _run(mats)
    bases = [
        {c.base_case_id for c in _inj(cases, e)}
        for e in ("nonexistent_source", "claim_text_mismatch", "other_edition_asserted")
    ]
    assert all(len(b) == 4 for b in bases)
    assert not (bases[0] & bases[1]) and not (bases[1] & bases[2]) and not (bases[0] & bases[2])


def test_make_cases_요지만_본_판례(mats):
    cases = _run(mats)
    cs = _inj(cases, "summary_as_full")
    assert [c.bundle.claims[0].sources[0].identifier for c in cs] == [
        "2001후100", "2003후300", "2004후400", "2005후500",
    ]  # fmt: skip
    c = cs[0]
    s = c.bundle.claims[0].sources[0]
    assert (c.base_case_id, c.bundle.oa_id, c.bundle.rejection) == (None, None, None)
    assert c.bundle.question.as_of is None
    assert c.bundle.question.source.value == "user_question"
    assert [k.value for k in c.bundle.question.source_kinds] == ["precedent"]
    assert c.bundle.claims[0].text == "가짜법원 2001후100 판결 전문은 다음과 같이 판단했다."
    assert s.evidence.document_id == "prec:1" and s.evidence.location == "전문"
    assert s.evidence.raw_text == "가짜 요지 첫째"  # 태그를 지우고 공백 정리
    assert (s.text_kind.value, s.speaker.value, s.court) == ("full", "court", "가짜법원")
    assert s.decided_on == date(2010, 2, 3)
    assert c.fix.text_kind.value == "summary"


def test_make_cases_옛_기한은_현행과_다른_가장_늦은_옛_판(mats):
    cases = _run(mats)
    cs = {
        c.bundle.claims[0].sources[0].identifier: c for c in _inj(cases, "old_deadline_as_current")
    }
    assert set(cs) == {
        "특허법 제52조제1항",
        "특허법 제53조제1항",
        "특허법 제67조의2제1항",
        "특허법 제132조의17",
    }
    # 52조: 현행 D3 3개월, 바로 앞 D2 2개월 -> D2
    c = cs["특허법 제52조제1항"]
    assert c.bundle.claims[0].text == "현행 특허법 제52조제1항의 기간은 2개월이다."
    assert c.bundle.question.text == "현행 특허법 제52조제1항의 기간은?"
    assert c.bundle.claims[0].sources[0].evidence.document_id == D2
    assert (c.fix.document_id, c.fix.raw_text_contains) == (D3, "3개월")
    assert c.bundle.question.as_of is None
    # 53조: D2도 3개월로 현행과 같다 -> 더 거슬러 D1(10일)
    c = cs["특허법 제53조제1항"]
    assert c.bundle.claims[0].sources[0].evidence.document_id == D1
    assert c.bundle.claims[0].text == "현행 특허법 제53조제1항의 기간은 10일이다."
    assert c.bundle.claims[0].sources[0].evidence.edition == f"{D1} 시행 2015-01-01 ~ 2017-12-31"


def test_make_cases_옛_기한을_못_찾으면_멈춘다(mats):
    # 52조 기간을 모든 판에서 같게 만든다
    for doc_id in (D1, D2):
        path = mats.law_raw / f"body_{doc_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["법령"]["조문"]["조문단위"][4]["항"][0]["항내용"] = "① 기한은 3개월 이내"
        _write_json(path, data)
    assert main(mats.args()) == 1
    assert not mats.out.exists()
