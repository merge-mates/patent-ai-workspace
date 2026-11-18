"""채점기 실행 전 검사 (requirements 기준 3, design.md 2절 2번·7-3)."""

import shutil
from pathlib import Path

import pytest

from eval.retrieval.checks import find_leaks, preflight
from eval.retrieval.config import load_config
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldItem, GoldRow, load_gold
from patent_ai.retrieval.repository import InMemoryChunkRepository

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repo():
    return InMemoryChunkRepository.from_jsonl("cite", FIX / "chunks_cite.jsonl")


@pytest.fixture
def goldsets_root(tmp_path):
    """임시 폴더에 정답 세트 구조(VERSION, tune/retrieval/)를 만든다."""
    root = tmp_path / "goldsets"
    (root / "tune" / "retrieval").mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    for f in FIX.glob("gold_*.jsonl"):
        shutil.copy(f, root / "tune" / "retrieval" / f.name)
    return root


def run_preflight(
    cfg,
    repo,
    root,
    *,
    gold_name="gold_ok.jsonl",
    chunks_mode=False,
    scores_dir=None,
    cq_dir=None,
    tmp=None,
):
    gold = load_gold(root / "tune" / "retrieval" / gold_name)
    preflight(
        cfg,
        gold,
        repo,
        root,
        chunks_mode=chunks_mode,
        scores_dir=scores_dir or (tmp / "scores"),
        cq_dir=cq_dir or (tmp / "cq"),
    )


def row(query, item):
    return GoldRow(row_id="r1", corpus="cite", query=query, items=[item])


PARA = GoldItem(kind="paragraph", start=23, end=23, label="[0023]")
FIG3 = GoldItem(kind="figure", figures=[3], label="도 3")
ART = GoldItem(kind="article", label="제29조 제2항")
COL = GoldItem(kind="column_line", start=30050, end=40005, label="3:50-4:5")


# ---- 평소: 통과 ----
def test_맞는_설정은_통과(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    run_preflight(cfg, repo, goldsets_root, tmp=tmp_path)


def test_빼는_줄_파일도_누출_없으면_통과(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    run_preflight(cfg, repo, goldsets_root, gold_name="gold_excluded.jsonl", tmp=tmp_path)


@pytest.mark.parametrize(
    "query,item",
    [
        ("온도 300℃에서 가열", FIG3),
        ("각도 30°로 기울인다", FIG3),
        ("농도 3%의 용액", FIG3),
        ("0.0023 중량%를 포함", PARA),
        ("0.0023 중량%를 포함", ART),
        ("중량비 3:10 으로 혼합", COL),
        ("제1항에 있어서, 상기 기판은", PARA),
        ("기판(110)과 전극(23)을 포함", PARA),
        ("도 3.5 mm 두께", FIG3),
    ],
)
def test_평소_청구항_글자는_누출로_안_본다(query, item):
    assert find_leaks(row(query, item)) == []


# ---- 누출 패턴 ----
@pytest.mark.parametrize(
    "query,item",
    [
        ("문단 [0023]에 있다", PARA),
        ("문단 [0022-0025]에 있다", PARA),
        ("문단 [23]에 있다", PARA),
        ("도 3 의 구조", FIG3),
        ("도3 의 구조", FIG3),
        ("도면 3 의 구조", FIG3),
        ("(도 3)과 같이", FIG3),
        ("FIG. 3 shows", FIG3),
        ("Fig.3 shows", FIG3),
        ("제29조 제2항에 따라", ART),
        ("29조 2항에 따라", ART),
        ("col. 3, l. 10", COL),
        ("칼럼 4 참조", COL),
    ],
)
def test_정답_위치_표기는_누출(query, item):
    assert len(find_leaks(row(query, item))) == 1


def test_다른_번호는_누출_아님():
    assert find_leaks(row("도 4 의 구조 [0030]", FIG3)) == []
    assert find_leaks(row("도 4 의 구조 [0030]", PARA)) == []


def test_누출_결과에_질의_글자가_없다():
    leaks = find_leaks(row("문단 [0023]에 적힌 비밀문구", PARA))
    assert leaks and all("비밀문구" not in s and "[0023]" not in s for s in leaks)


# ---- 실패 ----
def test_없는_색인_판은_실패(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_bad_index.yaml")
    with pytest.raises(RetrievalEvalError, match="cite-idx-v999"):
        run_preflight(cfg, repo, goldsets_root, tmp=tmp_path)


def test_정답_파일_0줄은_실패(goldsets_root):
    with pytest.raises(RetrievalEvalError, match="0줄"):
        load_gold(goldsets_root / "tune" / "retrieval" / "gold_empty.jsonl")


def test_정답_파일_없으면_실패(goldsets_root):
    with pytest.raises(RetrievalEvalError, match="없다"):
        load_gold(goldsets_root / "tune" / "retrieval" / "nope.jsonl")


def test_정답_세트_버전이_다르면_실패(repo, goldsets_root, tmp_path):
    (goldsets_root / "VERSION").write_text("2\n")
    cfg = load_config(FIX / "config_ok.yaml")
    with pytest.raises(RetrievalEvalError, match="goldset_version"):
        run_preflight(cfg, repo, goldsets_root, tmp=tmp_path)


def test_VERSION_파일이_없으면_실패(repo, goldsets_root, tmp_path):
    (goldsets_root / "VERSION").unlink()
    cfg = load_config(FIX / "config_ok.yaml")
    with pytest.raises(RetrievalEvalError, match="VERSION"):
        run_preflight(cfg, repo, goldsets_root, tmp=tmp_path)


@pytest.mark.parametrize("bad", ["../gold_ok.jsonl", "/etc/passwd", "retrieval/../../x.jsonl"])
def test_gold_경로가_세트_폴더_밖을_가리키면_실패(repo, goldsets_root, tmp_path, bad):
    cfg = load_config(FIX / "config_ok.yaml").model_copy(update={"gold": bad})
    with pytest.raises(RetrievalEvalError, match="gold"):
        run_preflight(cfg, repo, goldsets_root, tmp=tmp_path)


def test_누출_줄이_있으면_실패하고_row_id와_건수만_말한다(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    with pytest.raises(RetrievalEvalError) as e:
        run_preflight(cfg, repo, goldsets_root, gold_name="gold_leak.jsonl", tmp=tmp_path)
    msg = str(e.value)
    assert "3" in msg  # 누출 줄 3건
    assert "leak-para" in msg and "leak-fig" in msg and "leak-law" in msg
    assert "clean" not in msg
    for secret in ["가열 처리 방법", "기판 구조", "거절", "[0023]", "제29조"]:
        assert secret not in msg


def test_chunks_모드에서_scores_dir이_experiments_아래면_실패(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    with pytest.raises(RetrievalEvalError, match="experiments"):
        run_preflight(
            cfg,
            repo,
            goldsets_root,
            chunks_mode=True,
            scores_dir=REPO_ROOT / "experiments" / "x",
            tmp=tmp_path,
        )


def test_chunks_아니면_experiments_아래_scores_dir_통과(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    run_preflight(
        cfg,
        repo,
        goldsets_root,
        chunks_mode=False,
        scores_dir=REPO_ROOT / "experiments" / "x",
        tmp=tmp_path,
    )


# ---- --cq-dir: git 안에 들어갈 수 있으면 실패 ----
def test_cq_dir이_저장소_밖이면_통과(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    run_preflight(cfg, repo, goldsets_root, cq_dir=tmp_path / "cq", tmp=tmp_path)


def test_cq_dir이_저장소_안_무시_안_되는_경로면_실패(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    with pytest.raises(RetrievalEvalError, match="cq"):
        run_preflight(cfg, repo, goldsets_root, cq_dir=REPO_ROOT / "docs" / "x", tmp=tmp_path)


def test_cq_dir이_저장소_안_무시되는_경로면_통과(repo, goldsets_root, tmp_path):
    cfg = load_config(FIX / "config_ok.yaml")
    run_preflight(cfg, repo, goldsets_root, cq_dir=REPO_ROOT / "work" / "x", tmp=tmp_path)


# ---- 설정 읽기 ----
def test_설정_칸을_읽는다():
    cfg = load_config(FIX / "config_ok.yaml")
    assert (cfg.corpus, cfg.index_version, cfg.mode, cfg.impl) == (
        "cite",
        "cite-idx-v1",
        "bm25",
        "fake",
    )
    assert cfg.k == [1, 3, 5, 10]
    assert cfg.law_location_rule == "overlap_or_label"  # 생략하면 기본값


def test_설정에_필수_칸이_없으면_실패(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("experiment: x\n")
    with pytest.raises(RetrievalEvalError):
        load_config(p)


def test_정답_줄을_읽는다(goldsets_root):
    rows = load_gold(goldsets_root / "tune" / "retrieval" / "gold_ok.jsonl")
    assert len(rows) == 1
    assert rows[0].doc_ids == ["KR2000000001A"]
    assert [i.label for i in rows[0].items] == ["[0022-0025]", "도 3"]
