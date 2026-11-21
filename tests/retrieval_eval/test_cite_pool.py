"""노이즈 풀 표 만들기 (이슈 #178 T2, eval/GUIDE.md '인용문헌 둘째 점수 풀 표').

기대값은 GUIDE의 만드는 법에서 가져온다: 공보 첫 쪽의 (21) 출원번호(숫자만),
(43) 공개일자 또는 (45) 등록공고일, OA마다 우선일(없으면 출원일).
공보 글·번호는 모두 지어낸 값이다 (99로 시작하는 번호는 실제로 없음).
"""

from datetime import date

import pytest
import yaml

from eval.retrieval.cite_pool import build_pool, main, parse_front
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.noise_scope import PoolTable

KR_A = """(12) 공개특허공보(A)
H04N9/64(2006.01) (43) 공개일자 2007년04월25일
(21) 출원번호 99-2005-0000001
(22) 출원일자 2005년10월21일"""

KR_B = """(19) 대한민국특허청(KR) (45) 공고일자 2018년02월02일
(11) 등록번호 99-0000002
(12) 등록특허공보(B1)
(21) 출원번호 99-2017-0000002
(22) 출원일자 2017년01월05일"""

US_A = """(12) Patent Application Publication (10) Pub. No.: US 2099/0000003 A1
Kim et al. (43) Pub. Date: May 3, 2007
(21) Appl. No.: 99/000,003
(22) Filed: Nov. 2, 2005"""

US_B = """(12) United States Patent (10) Patent No.: US 9,900,004 B1
Lee et al. (45) Date of Patent: Feb. 13, 2007
(21) Appl. No.: 99/000,004 Assistant Examiner—Someone"""


@pytest.mark.parametrize(
    ("text", "app", "d"),
    [
        (KR_A, "9920050000001", date(2007, 4, 25)),
        (KR_B, "9920170000002", date(2018, 2, 2)),
        (US_A, "99000003", date(2007, 5, 3)),
        (US_B, "99000004", date(2007, 2, 13)),
        # 등록공보 첫 쪽에 (43) 공개일이 같이 찍히면 (45) 등록공고일을 쓴다 (#217 리뷰)
        (
            "(45) 공고일자 2019년09월10일\n(43) 공개일자 2019년03월08일\n"
            "(21) 출원번호 99-2017-0000008",
            "9920170000008",
            date(2019, 9, 10),
        ),
        # 출원번호 뒤에 다른 번호가 바로 붙어 나와도 출원번호만 읽는다
        (
            "(45) 공고일자 2018년02월07일\n(21) 출원번호 99-2016-0000006 99-0000007",
            "9920160000006",
            date(2018, 2, 7),
        ),
        # 스캔본: 글자 사이에 빈칸이 낀다
        (
            "(4 3 ) Pub . Date : Dec . 28 , 2017\n( 21 ) Appl. No. : 99 /0 00, 005 Some",
            "99000005",
            date(2017, 12, 28),
        ),
    ],
)
def test_공보_첫_쪽에서_출원번호와_공개일을_읽는다(text, app, d):
    assert parse_front(text) == (app, d)


def test_번호나_날짜가_없으면_멈춘다():
    with pytest.raises(RetrievalEvalError):
        parse_front("(12) 공개특허공보(A)\n아무 글")


def _setup(tmp_path, fronts: dict[str, dict[str, str]], cases: dict[str, str]):
    cited, proc = tmp_path / "cited", tmp_path / "cases"
    for app, docs in fronts.items():
        (cited / app).mkdir(parents=True)
        for doc_id, text in docs.items():
            (cited / app / f"{doc_id}.pdf").write_text(text, encoding="utf-8")  # 읽기는 가짜로 바꿈
    for app, oa in cases.items():
        (proc / app / oa).mkdir(parents=True)
    return cited, proc


def fake_reader(path):
    return path.read_text(encoding="utf-8")


def test_인용문헌_폴더와_사건_폴더로_풀_표를_만든다(tmp_path):
    cited, proc = _setup(
        tmp_path,
        {"PA": {"KR20990000001A": KR_A, "NPL2_paper": "논문"}, "PB": {"US20990000003A1": US_A}},
        {"PA": "OA1", "PB": "OA2", "PC": "OA3"},  # PC는 인용 특허가 없는 사건
    )
    prio = {"PA": date(2015, 1, 1), "PB": date(2016, 1, 1)}
    old = {"docs": {"NPL-paper-2012": {"app_no": None, "date": date(2012, 1, 1)}}, "oas": {}}
    table, rep = build_pool(cited, proc, prio, PoolTable.model_validate(old), read=fake_reader)
    assert table.docs["KR20990000001A"].app_no == "9920050000001"
    assert table.docs["US20990000003A1"].date == date(2007, 5, 3)
    # 비특허는 파일 이름이 doc_id가 아니라 옛 표에서 그대로 가져온다
    assert table.docs["NPL-paper-2012"].app_no is None
    assert set(table.oas) == {"OA1", "OA2"}
    assert table.oas["OA1"].app_no == "PA"
    assert rep["skipped_npl_files"] == 1


def test_우선일을_모르는_OA가_있으면_멈춘다(tmp_path):
    cited, proc = _setup(tmp_path, {"PA": {"KR20990000001A": KR_A}}, {"PA": "OA1"})
    with pytest.raises(RetrievalEvalError, match="우선일"):
        build_pool(cited, proc, {}, None, read=fake_reader)


def test_한_사건에_OA_폴더가_둘이면_멈춘다(tmp_path):
    cited, proc = _setup(tmp_path, {"PA": {"KR20990000001A": KR_A}}, {"PA": "OA1"})
    (proc / "PA" / "OA9").mkdir()
    with pytest.raises(RetrievalEvalError, match="OA 폴더"):
        build_pool(cited, proc, {"PA": date(2015, 1, 1)}, None, read=fake_reader)


def test_명령은_이미_있는_표를_덮지_않는다(tmp_path):
    root = tmp_path / "goldsets"
    (root / "tune" / "retrieval").mkdir(parents=True)
    out = root / "tune" / "retrieval" / "cite_pool_t30.yaml"
    out.write_text(yaml.safe_dump({"docs": {}, "oas": {}}), encoding="utf-8")
    argv = ["--goldsets-root", str(root), "--out", "retrieval/cite_pool_t30.yaml"]
    assert main(argv) == 1


def test_C안_노이즈_폴더는_사건_폴더로_보지_않는다(tmp_path):
    cited, proc = _setup(tmp_path, {"PA": {"KR20990000001A": KR_A}}, {"PA": "OA1"})
    (cited / "noise_c").mkdir()
    (cited / "noise_c" / "KR20990000009A.pdf").write_text("못 읽는 글", encoding="utf-8")
    table, _ = build_pool(cited, proc, {"PA": date(2015, 1, 1)}, None, read=fake_reader)
    assert set(table.docs) == {"KR20990000001A"}
