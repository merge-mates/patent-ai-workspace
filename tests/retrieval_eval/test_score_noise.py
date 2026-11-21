"""채점기 노이즈 범위 (이슈 #178 둘째 점수).

- 설정에 noise_scope가 없으면 주 점수(그 인용문헌 안) 그대로다.
- 있으면 줄마다 그 파일의 doc_id 범위에서 검색한다. 노이즈 문헌 조각은 맞음이 아니다.
- 문헌 Hit@k(상위 k개에 정답 문헌 조각이 있나)와 그 무작위 기준선을 더한다.
기대값은 아래 지어낸 조각에서 손으로 셌다 (구현을 보고 정하지 않음).
"""

import json
from math import comb

import pytest

from eval.retrieval.config import RetrievalEvalConfig
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.score import score
from patent_ai.retrieval.repository import InMemoryChunkRepository

IV = "cite-idx-v1"
GOLD_DOC, NOISE_DOC = "KR1000A", "KR2000A"
QUERY = "가열 냉각 기판"


def chunk(doc: str, n: int, text: str) -> dict:
    return {
        "chunk_id": f"{IV}:{doc}:[{n:04d}]",
        "index_version": IV,
        "doc_id": doc,
        "chunk_kind": "body",
        "location": {"kind": "paragraph", "start": n, "end": n, "label": f"[{n:04d}]"},
        "edition": {"status": "not_applicable"},
        "text": text,
    }


# fake bm25 = 질의 낱말 겹침 수. 노이즈 문단 1(3개 겹침)이 정답 문단 2(2개)보다 앞에 온다
CHUNKS = [
    chunk(GOLD_DOC, 1, "배경 설명"),
    chunk(GOLD_DOC, 2, "가열 냉각 단계"),  # 정답 위치
    chunk(GOLD_DOC, 3, "기타 설명"),
    chunk(NOISE_DOC, 1, "가열 냉각 기판"),
    chunk(NOISE_DOC, 2, "가열 다른 이야기"),
    chunk(NOISE_DOC, 3, "관련 없음"),
]
ROW_ID = f"OA1:r1:c1:{GOLD_DOC}"
GOLD_ROW = {
    "row_id": ROW_ID,
    "corpus": "cite",
    "query": QUERY,
    "doc_ids": [GOLD_DOC],
    "items": [{"kind": "paragraph", "start": 2, "end": 2, "label": "[0002]"}],
}


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "goldsets"
    d = root / "tune" / "retrieval"
    d.mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    (d / "gold.jsonl").write_text(json.dumps(GOLD_ROW, ensure_ascii=False) + "\n")
    (d / "noise.jsonl").write_text(
        json.dumps({"row_id": ROW_ID, "scope_doc_ids": [GOLD_DOC, NOISE_DOC]}) + "\n"
    )
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in CHUNKS))
    repo = InMemoryChunkRepository.from_jsonl("cite", chunks)
    return tmp_path, root, repo


def cfg(**over) -> RetrievalEvalConfig:
    base = {
        "experiment": "m2-i3-noise-fake",
        "goldset": "tune",
        "goldset_version": 1,
        "impl": "fake",
        "settings": {},
        "corpus": "cite",
        "index_version": IV,
        "mode": "bm25",
        "k": [1, 2],
        "gold": "retrieval/gold.jsonl",
    }
    base.update(over)
    return RetrievalEvalConfig.model_validate(base)


def run(env, c):
    tmp, root, repo = env
    return score(c, repo, root, "abc", scores_dir=tmp / "out", cq_dir=tmp / "cq").scores


def test_노이즈_설정이_없으면_그_문헌_안에서만_찾는다(env):
    s = run(env, cfg())
    # 정답 문헌 안에서는 문단 2가 1등
    assert s["metrics"]["hit@1"] == 1.0
    assert "doc_hit@1" not in s["metrics"]
    assert "scope" not in s


def test_노이즈를_섞으면_노이즈_조각은_맞음이_아니다(env):
    s = run(env, cfg(noise_scope="retrieval/noise.jsonl"))
    m = s["metrics"]
    # 1등 = 노이즈 문단 1(틀림), 2등 = 정답 문단 2
    assert m["hit@1"] == 0.0
    assert m["hit@2"] == 1.0
    assert m["doc_hit@1"] == 0.0
    assert m["doc_hit@2"] == 1.0
    # 무작위 기준선 분모 N = 정답+노이즈 조각 6개. 정답 조각 1개, 정답 문헌 조각 3개
    assert m["random_hit@1"] == pytest.approx(1 / 6)
    assert m["random_hit@2"] == pytest.approx(1 - comb(5, 2) / comb(6, 2))
    assert m["random_doc_hit@1"] == pytest.approx(3 / 6)
    assert m["random_doc_hit@2"] == pytest.approx(1 - comb(3, 2) / comb(6, 2))
    assert s["scope"]["kind"] == "noise"
    assert s["scope"]["file"] == "retrieval/noise.jsonl"
    assert s["scope"]["docs_per_row_mean"] == 2.0
    assert len(s["scope"]["sha256"]) == 64


def test_범위_파일에_줄이_없으면_멈춘다(env):
    tmp, root, _ = env
    (root / "tune" / "retrieval" / "noise.jsonl").write_text(
        json.dumps({"row_id": "OA9:r1:c1:KR9A", "scope_doc_ids": ["KR9A"]}) + "\n"
    )
    with pytest.raises(RetrievalEvalError, match=ROW_ID):
        run(env, cfg(noise_scope="retrieval/noise.jsonl"))


def test_범위에_정답_문헌이_빠지면_멈춘다(env):
    tmp, root, _ = env
    (root / "tune" / "retrieval" / "noise.jsonl").write_text(
        json.dumps({"row_id": ROW_ID, "scope_doc_ids": [NOISE_DOC]}) + "\n"
    )
    with pytest.raises(RetrievalEvalError, match="정답 문헌"):
        run(env, cfg(noise_scope="retrieval/noise.jsonl"))


def test_정답_문헌_본문이_없으면_노이즈가_있어도_본문_없음으로_뺀다(env):
    tmp, root, _ = env
    other = {**GOLD_ROW, "row_id": "OA1:r1:c2:KR9999A", "doc_ids": ["KR9999A"]}
    (root / "tune" / "retrieval" / "gold.jsonl").write_text(
        json.dumps(GOLD_ROW, ensure_ascii=False)
        + "\n"
        + json.dumps(other, ensure_ascii=False)
        + "\n"
    )
    (root / "tune" / "retrieval" / "noise.jsonl").write_text(
        json.dumps({"row_id": ROW_ID, "scope_doc_ids": [GOLD_DOC, NOISE_DOC]})
        + "\n"
        + json.dumps({"row_id": "OA1:r1:c2:KR9999A", "scope_doc_ids": ["KR9999A", NOISE_DOC]})
        + "\n"
    )
    s = run(env, cfg(noise_scope="retrieval/noise.jsonl"))
    assert s["n"] == 1
    assert s["failures"]["excluded_body_missing"] == 1


def test_노이즈_범위는_인용문헌만(env):
    with pytest.raises(ValueError):
        cfg(corpus="law", index_version="law-idx-v1", noise_scope="retrieval/noise.jsonl")


def test_노이즈_범위_경로는_세트_폴더_안만(env):
    with pytest.raises(RetrievalEvalError):
        run(env, cfg(noise_scope="../noise.jsonl"))
