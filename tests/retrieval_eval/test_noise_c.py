"""C안 노이즈 후보 고르기 (이슈 #178 T2).

기대값은 이슈 #178에서 가져온다: OA마다 같은 IPC·청구항과 낱말이 비슷한 한국 공보 5건,
그 출원의 우선일 전에 공개된 것만, 그 출원 자신·정답 인용문헌과 같은 특허의 공보는 뺀다.
정답 인용문헌은 모두 풀 표(B안)에 있으니, 풀 표의 어느 문헌과 같은 특허여도 뺀다 (더 넓게 뺌).
C안 문헌은 그 OA의 줄에만 넣는다 (11/21 은진 결정, 풀 표 `only_oas`).
XML은 KIPRIS Plus 공보 검색 응답 꼴을 흉내 낸 지어낸 값이다 (번호는 실제로 없는 99·2099 꼴).
"""

from datetime import date

import pytest
import yaml

from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.noise_c import (
    Hit,
    main,
    parse_search_xml,
    pick_candidates,
    suggest_words,
)
from eval.retrieval.noise_scope import PoolOa, PoolTable


def item(app: str, open_no: str = "", open_d: str = "", reg_no: str = "", reg_d: str = "") -> str:
    return (
        "<item>"
        f"<applicationNumber>{app}</applicationNumber>"
        f"<openNumber>{open_no}</openNumber><openDate>{open_d}</openDate>"
        f"<registerNumber>{reg_no}</registerNumber><registerDate>{reg_d}</registerDate>"
        "<inventionTitle>가짜 명칭</inventionTitle>"
        "</item>"
    )


def xml(*items: str, code: str = "00") -> str:
    return (
        "<response><header>"
        f"<resultCode>{code}</resultCode><resultMsg>NORMAL SERVICE.</resultMsg>"
        "</header><body><items>" + "".join(items) + "</items></body></response>"
    )


def test_응답을_읽어_공개번호로_doc_id를_만든다():
    hits = parse_search_xml(
        xml(
            item("9920970000001", "9920990000001", "20110105"),
            # 공개 없이 등록만 있는 공보는 등록번호 앞 9자리 + B1
            item("9920970000002", reg_no="9912345670000", reg_d="20120301"),
        )
    )
    assert hits == [
        Hit(doc_id="KR20990000001A", app_no="9920970000001", date=date(2011, 1, 5)),
        Hit(doc_id="KR991234567B1", app_no="9920970000002", date=date(2012, 3, 1)),
    ]


def test_응답_코드가_정상이_아니면_멈춘다():
    with pytest.raises(RetrievalEvalError, match="99"):
        parse_search_xml(xml(code="99"))


def test_공개도_등록도_없는_항목은_건너뛴다():
    assert parse_search_xml(xml(item("9920970000003"))) == []


OA = PoolOa(app_no="PA", priority_date=date(2015, 1, 1))


def hit(n: int, app: str | None = None, d: date = date(2012, 1, 1)) -> Hit:
    return Hit(doc_id=f"KR2099000000{n}A", app_no=app or f"P{n}", date=d)


def test_넣는_조건대로_걸러_앞에서_5건을_고른다():
    hits = [
        hit(1, app="PA"),  # 그 출원 자신
        hit(2, app="PG"),  # 풀에 이미 있는 특허 (정답 인용문헌 등)와 같은 특허
        hit(3, d=date(2015, 1, 1)),  # 우선일 당일
        hit(4),
        hit(5),
        hit(6),
        hit(7),
        hit(8),
        hit(9),
    ]
    picked = pick_candidates(hits, OA, known_apps={"PG"}, known_doc_ids=set(), n=5)
    assert [h.doc_id for h in picked] == [f"KR2099000000{i}A" for i in (4, 5, 6, 7, 8)]


def test_풀에_이미_있는_문헌과_같은_번호는_다시_넣지_않는다():
    hits = [hit(4), hit(4), hit(5)]
    picked = pick_candidates(hits, OA, known_apps=set(), known_doc_ids={"KR20990000005A"}, n=5)
    assert [h.doc_id for h in picked] == ["KR20990000004A"]


def test_청구항_낱말을_자주_나온_순으로_고른다():
    claim = (
        "영상을 촬영하는 카메라부; 상기 영상에서 객체를 검출하는 검출부; "
        "상기 객체의 위치를 상기 영상에 표시하는 표시부를 포함하는 영상 처리 장치."
    )
    # '상기'·'포함하는'·'장치' 같은 말은 빼고, 조사(을·에서·의·를)를 뗀 낱말을 센다
    assert suggest_words(claim, n=3) == ["영상", "객체", "카메라부"]


# --- 명령: 저장해 둔 응답 폴더 + 풀 표 + 질의 표 → C안을 더한 새 풀 표 ---


@pytest.fixture
def setroot(tmp_path):
    root = tmp_path / "goldsets"
    d = root / "tune" / "retrieval"
    d.mkdir(parents=True)
    pool = {
        "docs": {"KR20980000001A": {"app_no": "PG", "date": "2009-01-01"}},
        "oas": {"OA1": {"app_no": "PA", "priority_date": "2015-01-01"}},
    }
    (d / "cite_pool.yaml").write_text(yaml.safe_dump(pool), encoding="utf-8")
    (d / "cite_c_queries.yaml").write_text(
        yaml.safe_dump(
            {"OA1": {"ipc": "G06T 7/11", "words": ["영상", "객체"]}}, allow_unicode=True
        ),
        encoding="utf-8",
    )
    resp = tmp_path / "kipris_c"
    resp.mkdir()
    (resp / "OA1.xml").write_text(
        xml(
            item("PG", "9920980000009", "20090601"),  # 정답과 같은 특허
            item("P4", "9920990000004", "20110101"),
        ),
        encoding="utf-8",
    )
    return root, resp


def test_명령은_C안을_더한_새_풀_표를_쓴다(setroot):
    root, resp = setroot
    argv = ["--goldsets-root", str(root), "--responses", str(resp)]
    assert main(argv) == 0
    out = root / "tune" / "retrieval" / "cite_pool_bc.yaml"
    table = PoolTable.model_validate(yaml.safe_load(out.read_text(encoding="utf-8")))
    assert table.docs["KR20990000004A"].only_oas == ["OA1"]
    assert "KR20980000009A" not in table.docs
    # 원래 풀 표는 덮지 않는다
    orig = yaml.safe_load((root / "tune" / "retrieval" / "cite_pool.yaml").read_text())
    assert list(orig["docs"]) == ["KR20980000001A"]


def test_응답_파일이_없는_OA가_있으면_멈춘다(setroot):
    root, resp = setroot
    (resp / "OA1.xml").unlink()
    assert main(["--goldsets-root", str(root), "--responses", str(resp)]) == 1
    assert not (root / "tune" / "retrieval" / "cite_pool_bc.yaml").exists()


# --- 질의 표 초안: OA 당시 청구항 1에서 낱말, 사건 목록 CSV에서 IPC ---

from eval.retrieval.noise_c import claim1_text, draft_queries  # noqa: E402

SEP = "¶"


def history(*rows: tuple[str, str, str]) -> str:
    head = SEP.join(
        [
            "출원번호",
            "접수발송일련번호",
            "접수발송번호",
            "청구항번호",
            "변경구분코드",
            "변경구분명",
            "청구항",
            "변동대상접수문서번호",
            "변동청구항",
        ]
    )
    body = [SEP.join(["PA", "1", "R1", no, code, "", text, " ", " "]) for no, code, text in rows]
    return "\n".join([head, *body]) + "\n"


def test_청구항_이력에서_마지막_1항을_읽는다():
    h = history(
        ("1", "I", "옛 영상 장치"), ("2", "I", "제1항에 있어서"), ("1", "M", "새 영상 장치")
    )
    assert claim1_text(h) == "새 영상 장치"


def test_질의_표_초안은_컴퓨터_비전_IPC를_먼저_쓰고_낱말을_뽑는다(tmp_path):
    case = tmp_path / "cases" / "PA" / "OA1"
    case.mkdir(parents=True)
    (case / "PA_청구항이력.txt").write_text(
        history(("1", "I", "영상을 받는 카메라; 상기 영상의 객체를 찾는 검출부")), encoding="utf-8"
    )
    csv = tmp_path / "list.csv"
    csv.write_text(
        "﻿출원번호,OA발송번호,IPC,CV_IPC\nPA,OA1,B60R 1/00;G06T 7/11;G06V 10/00,Y\n",
        encoding="utf-8",
    )
    oas = {"OA1": PoolOa(app_no="PA", priority_date=date(2015, 1, 1))}
    q = draft_queries(oas, tmp_path / "cases", csv, n_words=2)
    assert q == {"OA1": {"ipc": "G06T 7/11", "words": ["영상", "카메라"]}}


def test_어디에나_나오는_말과_꾸밈말은_낱말에서_뺀다():
    claim = "복수의 신호들을 수신하는 단계; 수신된 신호들에서 혈류 영역을 찾는 단계를 포함하는 방법"
    assert suggest_words(claim, n=3) == ["신호", "혈류", "영역"]


def test_질의_낱말이_명칭과_요약에_많이_나온_순으로_고른다():
    # 11/21 첫 실호출: 응답이 검색 순위가 아니라 최근 순에 가까웠다.
    # 그래서 낱말 겹침으로 다시 줄 세운다
    hits = [
        Hit(doc_id="KR20990000001A", app_no="P1", date=date(2012, 1, 1), text="신호처리 장치"),
        Hit(doc_id="KR20990000002A", app_no="P2", date=date(2012, 1, 1), text="MR 혈류 영상 혈류"),
        Hit(doc_id="KR20990000003A", app_no="P3", date=date(2012, 1, 1), text="혈류 측정"),
    ]
    picked = pick_candidates(hits, OA, set(), set(), n=2, words=["혈류", "MR"])
    assert [h.doc_id for h in picked] == ["KR20990000002A", "KR20990000003A"]


def test_응답의_명칭과_요약을_글로_남긴다():
    body = xml(
        "<item><applicationNumber>P9</applicationNumber><openNumber>9920990000009</openNumber>"
        "<openDate>20110105</openDate><inventionTitle>혈류 영상</inventionTitle>"
        "<astrtCont>MR 신호</astrtCont></item>"
    )
    assert parse_search_xml(body)[0].text == "혈류 영상 MR 신호"
