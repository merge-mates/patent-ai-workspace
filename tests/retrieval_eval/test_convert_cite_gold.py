"""정답 변환 (design 3-1). 지어낸 정답 JSON·청구항이력만 쓰고, 출력은 전부 tmp_path."""

import hashlib
import json
import logging
import shutil
from pathlib import Path

import pytest

from eval.retrieval.convert_cite_gold import main
from eval.retrieval.gold import load_gold
from eval.retrieval.matchers import CiteMatcher
from patent_ai.retrieval.schemas import Chunk, Edition, Location

FIX = Path(__file__).parent.parent / "fixtures" / "cite_search"
OA = "9-5-2099-0000002"
KR1 = "KR2099000001A"
NPL = "NPL-MadeUp-Conf2099"
OUT_REL = Path("tune/retrieval/cite_gold.jsonl")


class Env:
    """한 테스트가 쓰는 임시 폴더 묶음."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.goldsets = tmp_path / "goldsets"
        shutil.copytree(FIX / "goldsets", self.goldsets)
        self.cases = tmp_path / "cases"
        shutil.copytree(FIX / "cases", self.cases)
        self.src = tmp_path / "gold.json"
        shutil.copy(FIX / "gold.json", self.src)
        self.report = tmp_path / "work" / "report.json"
        self.out = self.goldsets / OUT_REL
        self.version = self.goldsets / "VERSION"

    def data(self) -> dict:
        return json.loads(self.src.read_text(encoding="utf-8"))

    def write_src(self, data: dict) -> None:
        self.src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def run(self) -> int:
        return main(
            [
                "--src", str(self.src),
                "--cases", str(self.cases),
                "--goldsets-root", str(self.goldsets),
                "--report", str(self.report),
            ]
        )  # fmt: skip

    def rows(self) -> dict:
        return {r.row_id: r for r in load_gold(self.out)}


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def rid(r, c, doc, oa=OA):
    return f"{oa}:r{r}:c{c}:{doc}"


def chunk(doc_id, kind="paragraph", chunk_kind="body", start=None, end=None, figures=(), claims=()):
    return Chunk(
        chunk_id=f"v1:{doc_id}:x",
        index_version="v1",
        doc_id=doc_id,
        chunk_kind=chunk_kind,
        location=Location(
            kind=kind,
            start=start,
            end=end,
            label="x",
            figures=list(figures),
            claims=list(claims),
        ),
        edition=Edition(status="not_applicable"),
        text="지어낸 본문",
    )


# ---- 평소 ----


def test_정상_변환은_줄_일곱_개를_쓰고_다시_읽힌다(env):
    assert env.run() == 0
    rows = env.rows()
    assert set(rows) == {
        rid(1, 1, KR1),
        rid(1, 2, KR1),
        rid(1, 3, KR1),
        rid(1, 4, KR1),
        rid(1, 6, KR1),
        rid(1, 1, NPL),
        rid(3, 1, "KR2099000002B1"),
    }
    assert all(r.corpus == "cite" for r in rows.values())
    assert rows[rid(1, 1, KR1)].doc_ids == [KR1]
    assert rows[rid(1, 1, NPL)].doc_ids == [NPL]


def test_범위_키와_식별번호_범위는_펼쳐_복사한다(env):
    env.run()
    rows = env.rows()
    # "3-4" -> 줄 둘, 항목은 같다
    assert rows[rid(1, 3, KR1)].items == rows[rid(1, 4, KR1)].items
    c1 = rows[rid(1, 1, KR1)].items
    para = [i for i in c1 if i.kind == "paragraph"]
    assert [(i.start, i.end) for i in para] == [(21, 21), (22, 25)]
    figs = [i.figures for i in c1 if i.kind == "figure"]
    assert figs == [[3], [4]]  # "4c"는 4
    assert any(i.kind == "abstract" for i in c1)
    c3 = rows[rid(1, 3, KR1)].items
    claim_items = [i.claims for i in c3 if i.kind == "claim"]
    assert claim_items == [[1], [12, 13, 14]]


def test_항목이_같은_위치의_조각을_CiteMatcher가_맞다고_본다(env):
    env.run()
    rows = env.rows()
    m = CiteMatcher()
    row1 = rows[rid(1, 1, KR1)]
    by_kind = {i.kind: i for i in row1.items}
    assert m.matches(chunk(KR1, start=23, end=23), row1.items[1], row1)  # [0022]-[0025]
    assert m.matches(chunk(KR1, kind="figure", figures=[3]), row1.items[2], row1)
    assert m.matches(chunk(KR1, chunk_kind="abstract", kind="abstract"), by_kind["abstract"], row1)
    row3 = rows[rid(1, 3, KR1)]
    claim_item = [i for i in row3.items if i.claims == [12, 13, 14]][0]
    assert m.matches(chunk(KR1, kind="claim", chunk_kind="claim", claims=[13]), claim_item, row3)
    rown = rows[rid(1, 1, NPL)]
    assert rown.items[0].kind == "page"
    assert (rown.items[0].start, rown.items[0].end) == (3, 3)
    assert m.matches(chunk(NPL, kind="page", start=3, end=3), rown.items[0], rown)
    assert not m.matches(chunk(NPL, kind="page", start=4, end=4), rown.items[0], rown)


def test_질의는_OA_당시_청구항이고_OA_뒤_보정은_안_들어간다(env):
    env.run()
    rows = env.rows()
    assert rows[rid(1, 1, KR1)].query == (
        "시료를 가열하는 단계와 기판을 냉각하는 단계를 포함하는 처리 방법.\n추가 줄 하나."
    )
    assert rows[rid(1, 3, KR1)].query == "세번째 청구항 OA 전 보정 글자."
    assert all("OA 뒤" not in r.query for r in rows.values())


def test_사건_폴더의_등록공보와_결정본문은_질의에_영향이_없다(env):
    # 등록공보.pdf 안에는 OA 뒤 글자가 있다. 지워도 결과가 같아야 읽지 않은 것이다
    env.run()
    before = env.out.read_bytes()
    for name in ("등록공보.pdf", "결정본문.txt"):
        (env.cases / "10-2099-0000001" / name).unlink()
    env.out.unlink()
    env.version.unlink()
    assert env.run() == 0
    assert env.out.read_bytes() == before


def test_VERSION은_없으면_1이고_같은_입력을_다시_돌려도_안_오른다(env):
    env.run()
    assert env.version.read_text().strip() == "1"
    env.run()
    assert env.version.read_text().strip() == "1"


def test_내용이_바뀌면_VERSION이_오른다(env):
    env.run()
    data = env.data()
    data["사건"][0]["거절이유"][2]["인용"][0]["청구항별"]["1"]["식별번호"] = ["0008"]
    env.write_src(data)
    env.run()
    assert env.version.read_text().strip() == "2"
    sha = hashlib.sha256(env.out.read_bytes()).hexdigest()
    env.run()
    assert hashlib.sha256(env.out.read_bytes()).hexdigest() == sha
    assert env.version.read_text().strip() == "2"


def test_변환_보고가_work에_남는다(env):
    env.run()
    rep = json.loads(env.report.read_text(encoding="utf-8"))
    assert rep["rows"] == 7
    assert rep["expanded"] == 2  # "3-4" -> 2줄
    assert rep["excluded"] == {"same_as_other": 1, "no_location": 1}
    assert rep["no_query_cases"] == 2  # 청구항이력 없는 사건 + OA 없는 사건
    assert rep["no_query_rows"] == 2
    assert rep["claim_missing_rows"] == 1  # 5항은 OA 앞에 삭제됨
    assert rep["unapplied_changes"] == 1


# ---- 빈 입력 ----


def test_같은이유는_same_as_other_위치없음은_no_location_줄이다(env, caplog):
    with caplog.at_level(logging.WARNING):
        env.run()
    rows = env.rows()
    same = rows[rid(1, 6, KR1)]
    assert same.exclude == "same_as_other"
    assert same.items == []
    assert same.query == "여섯번째 청구항 처음 글자."
    noloc = rows[rid(1, 2, KR1)]
    assert noloc.exclude == "no_location"
    assert noloc.items == []
    # 이미 청구항별에 있는 4항은 같은이유에 있어도 same_as_other가 아니다
    assert rows[rid(1, 4, KR1)].exclude is None
    assert any(rid(1, 2, KR1) in r.message for r in caplog.records)


def test_42조는_줄이_없다(env):
    env.run()
    assert not [k for k in env.rows() if ":r2:" in k]


def test_청구항이력_없는_사건은_줄이_없고_경고한다(env, caplog):
    with caplog.at_level(logging.WARNING):
        env.run()
    assert not [k for k in env.rows() if "9-5-2099-0000007" in k]
    last = caplog.records[-1]
    assert last.levelno == logging.WARNING
    assert "no_location" in last.message and "same_as_other" in last.message


def test_OA_발송번호가_행정이력에_없으면_그_사건만_뺀다(env):
    assert env.run() == 0
    assert not [k for k in env.rows() if "9-5-2099-9999999" in k]


def test_삭제된_청구항은_그_줄만_뺀다(env):
    env.run()
    assert rid(1, 5, KR1) not in env.rows()


def test_결과가_0줄이면_종료_1이고_파일을_안_쓴다(env):
    data = env.data()
    data["사건"] = data["사건"][1:2]  # 청구항이력 없는 사건 하나뿐
    env.write_src(data)
    assert env.run() == 1
    assert not env.out.exists() and not env.version.exists()


# ---- 실패 ----


def _bump_claim_text(env, text):
    p = env.cases / "10-2099-0000001" / "10-2099-0000001_청구항이력.txt"
    s = p.read_text(encoding="utf-8")
    p.write_text(
        s.replace("시료를 가열하는 단계와", f"{text} 시료를 가열하는 단계와"), encoding="utf-8"
    )


def test_질의에_정답_위치_표기가_있으면_종료_1_파일과_VERSION_그대로(env, capsys):
    env.run()
    before_out, before_ver = env.out.read_bytes(), env.version.read_text()
    _bump_claim_text(env, "[0023]")  # 정답 [0022]-[0025]와 겹침
    assert env.run() == 1
    assert env.out.read_bytes() == before_out
    assert env.version.read_text() == before_ver
    err = capsys.readouterr().err
    assert rid(1, 1, KR1) in err
    assert "시료를 가열" not in err  # 질의 글자는 안 찍는다


def test_표에_없는_문헌은_종료_1(env):
    data = env.data()
    data["사건"][0]["거절이유"][0]["인용"][1]["문헌"] = "NPL9 Unknown Paper (Conf 2099)"
    env.write_src(data)
    assert env.run() == 1
    assert not env.out.exists()


def test_논문_쪽이_표의_쪽_수보다_크면_종료_1(env):
    data = env.data()
    data["사건"][0]["거절이유"][0]["인용"][1]["청구항별"]["1"]["기타"] = ["10쪽 1절"]
    env.write_src(data)
    assert env.run() == 1
    assert not env.out.exists()


def test_doc_id에_콜론이나_공백이_있으면_종료_1(env):
    (env.goldsets / "tune/retrieval/cite_doc_ids.yaml").write_text(
        '"NPL1 Made Up Title (Conf 2099, pp.1-9)":\n  doc_id: "NPL: Bad Id"\n  pages: 9\n',
        encoding="utf-8",
    )
    assert env.run() == 1


def test_row_id가_중복되면_종료_1(env):
    data = env.data()
    # 같은 인용문헌이 한 거절이유에 두 번 나오면 같은 row_id
    cites = data["사건"][0]["거절이유"][2]["인용"]
    cites.append(dict(cites[0]))
    env.write_src(data)
    assert env.run() == 1
    assert not env.out.exists()
