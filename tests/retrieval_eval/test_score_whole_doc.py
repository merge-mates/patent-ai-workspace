"""채점기에 문헌 통째 LLM impl 연결 (이슈 #248 T2). 가짜 전송층만 쓴다: 네트워크·API 키 없음.

가격은 config/cite_rank.yaml의 whole_doc 칸: 입력 100만 토큰당 $0.10, 출력 $0.50.
가짜 응답 한 번 = 입력 100토큰 + 출력 10토큰 = (100*0.10 + 10*0.50) / 1e6 = $0.000015.
"""

import json
import shutil
from pathlib import Path

import pytest

from eval.retrieval import score as score_mod
from eval.retrieval.config import load_config
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.score import main, score
from patent_ai.core.llm.cache import MemoryCache
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.retrieval.repository import InMemoryChunkRepository

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval"
CHECK_CHUNKS = FIX / "chunks_check.jsonl"
STEP = "cite_rank.whole_doc"
CALL_USD = 0.000015  # 호출 한 번의 비용 (위 설명)


def answer(text: str) -> TransportResponse:
    return TransportResponse(text=text, input_tokens=100, output_tokens=10, stop_reason="end_turn")


def ranked(*nums: int) -> TransportResponse:
    return answer(json.dumps({"ranked": list(nums)}))


@pytest.fixture
def goldsets_root(tmp_path):
    root = tmp_path / "goldsets"
    (root / "tune" / "retrieval").mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    for f in FIX.glob("gold_*.jsonl"):
        shutil.copy(f, root / "tune" / "retrieval" / f.name)
    return root


def make_ctx(responses, cache=None):
    return RunContext(
        run_id="r_test",
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=FakeTransport({STEP: responses}),
        cache=cache,
    )


def make_cfg(tmp_path, extra="", settings_extra=""):
    text = (FIX / "config_whole_doc.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(text + settings_extra + extra, encoding="utf-8")
    return path


def run_score(tmp_path, goldsets_root, ctx, extra="", settings_extra=""):
    cfg = load_config(make_cfg(tmp_path, extra, settings_extra))
    repo = InMemoryChunkRepository.from_jsonl("cite", CHECK_CHUNKS)
    return score(
        cfg,
        repo,
        goldsets_root,
        "abc",
        scores_dir=tmp_path / "out",
        cq_dir=tmp_path / "cq",
        run_context=ctx,
    )


def test_2줄을_채점하면_cost_칸에_호출수_토큰_usd가_찬다(tmp_path, goldsets_root):
    ctx = make_ctx([ranked(1), ranked(2)])
    scores = run_score(tmp_path, goldsets_root, ctx).scores
    cost = scores["cost"]
    assert cost["external_calls"] == 2
    assert cost["model_calls"] == 2
    assert cost["cache_hits"] == 0
    assert cost["input_tokens"] == 200
    assert cost["output_tokens"] == 20
    assert cost["usd"] == pytest.approx(2 * CALL_USD)
    assert scores["n"] == 2
    assert scores["failures"]["llm_output_invalid"] == 0
    assert scores["failures"]["not_extracted"] == 0


def test_캐시_적중은_실제_호출과_비용에_안_센다(tmp_path, goldsets_root):
    cache = MemoryCache()
    run_score(tmp_path, goldsets_root, make_ctx([ranked(1), ranked(2)], cache))
    # 같은 캐시로 다시 돌리면 전송층을 안 부른다 (가짜 답 목록은 비어 있어도 됨)
    again = make_ctx([], cache)
    cost = run_score(tmp_path, goldsets_root, again).scores["cost"]
    assert cost["external_calls"] == 0
    assert cost["model_calls"] == 2
    assert cost["cache_hits"] == 2
    assert (cost["input_tokens"], cost["output_tokens"], cost["usd"]) == (0, 0, 0)


def test_출력_검사_실패는_호출에_세고_failures에_드러난다(tmp_path, goldsets_root):
    # 첫 줄: 실패 1번 뒤 성공. 둘째 줄: 2번 다 실패 -> not_extracted로 점수에서 빠진다
    ctx = make_ctx([answer("깨짐"), ranked(1), answer("틀림"), answer("또 틀림")])
    scores = run_score(tmp_path, goldsets_root, ctx).scores
    assert scores["cost"]["external_calls"] == 4
    assert scores["failures"]["llm_output_invalid"] == 3
    assert scores["failures"]["not_extracted"] == 1
    assert scores["failures"]["excluded_body_missing"] == 0
    assert scores["n"] == 1


def test_가격을_모르는_호출이_있으면_usd는_None이고_0으로_메우지_않는다(tmp_path, goldsets_root):
    cfgdir = tmp_path / "llmcfg"
    cfgdir.mkdir()
    (cfgdir / "cite_rank.yaml").write_text(
        "whole_doc:\n  model: m\n  effort: low\n  max_tokens: 100\n"
        "  prompt: prompts/cite_rank/whole_doc.md\n  max_model_calls: 10\n",
        encoding="utf-8",
    )
    ctx = make_ctx([ranked(1), ranked(2)])
    cost = run_score(
        tmp_path, goldsets_root, ctx, settings_extra=f"  config_dir: {cfgdir}\n"
    ).scores["cost"]
    assert cost["usd"] is None
    assert cost["input_tokens"] == 200  # 토큰은 앎


def test_호출_수_상한에_닿으면_다음_줄_전에_멈춘다(tmp_path, goldsets_root):
    ctx = make_ctx([ranked(1), ranked(2)])
    with pytest.raises(RetrievalEvalError, match="max_external_calls"):
        run_score(tmp_path, goldsets_root, ctx, extra="budget:\n  max_external_calls: 1\n")
    assert len(ctx.transport.calls) == 1  # 첫 줄만 불렀다


def test_usd_상한에_닿으면_다음_줄_전에_멈춘다(tmp_path, goldsets_root):
    ctx = make_ctx([ranked(1), ranked(2)])
    # 첫 줄 뒤 $0.000015 >= 상한 $0.00001
    with pytest.raises(RetrievalEvalError, match="max_usd"):
        run_score(tmp_path, goldsets_root, ctx, extra="budget:\n  max_usd: 0.00001\n")
    assert len(ctx.transport.calls) == 1


def test_상한에_닿으면_main이_1이고_scores_json을_안_쓴다(tmp_path, goldsets_root, monkeypatch):
    ctx = make_ctx([ranked(1), ranked(2)])
    monkeypatch.setattr(score_mod, "new_run_context", lambda cfg, cache_dir: ctx)
    cfg = make_cfg(tmp_path, "budget:\n  max_external_calls: 1\n")
    argv = [
        "--config", str(cfg),
        "--goldsets-root", str(goldsets_root),
        "--chunks", str(CHECK_CHUNKS),
        "--scores-dir", str(tmp_path / "out"),
        "--cq-dir", str(tmp_path / "cq"),
        "--cache-dir", str(tmp_path / "cache"),
    ]  # fmt: skip
    assert main(argv, commit="abc", ignored=lambda p: True) == 1
    assert not (tmp_path / "out" / "scores.json").exists()


def test_main이_끝까지_돌면_cost가_scores_json에_쓰인다(tmp_path, goldsets_root, monkeypatch):
    ctx = make_ctx([ranked(1), ranked(2)])
    monkeypatch.setattr(score_mod, "new_run_context", lambda cfg, cache_dir: ctx)
    argv = [
        "--config", str(make_cfg(tmp_path)),
        "--goldsets-root", str(goldsets_root),
        "--chunks", str(CHECK_CHUNKS),
        "--scores-dir", str(tmp_path / "out"),
        "--cq-dir", str(tmp_path / "cq"),
        "--cache-dir", str(tmp_path / "cache"),
    ]  # fmt: skip
    assert main(argv, commit="abc", ignored=lambda p: True) == 0
    saved = json.loads((tmp_path / "out" / "scores.json").read_text(encoding="utf-8"))
    assert saved["cost"]["external_calls"] == 2
    assert saved["impl"] == "whole_doc_llm"


def test_cache_dir_없으면_채점_전에_1로_멈춘다(tmp_path, goldsets_root, capsys):
    argv = [
        "--config", str(make_cfg(tmp_path)),
        "--goldsets-root", str(goldsets_root),
        "--chunks", str(CHECK_CHUNKS),
        "--scores-dir", str(tmp_path / "out"),
        "--cq-dir", str(tmp_path / "cq"),
    ]  # fmt: skip
    assert main(argv, commit="abc", ignored=lambda p: True) == 1
    assert "--cache-dir" in capsys.readouterr().err
    assert not (tmp_path / "out" / "scores.json").exists()


def test_cache_dir이_git_제외가_아니면_1이고_아무것도_안_쓴다(tmp_path, goldsets_root, capsys):
    cache = tmp_path / "cache"
    argv = [
        "--config", str(make_cfg(tmp_path)),
        "--goldsets-root", str(goldsets_root),
        "--chunks", str(CHECK_CHUNKS),
        "--scores-dir", str(tmp_path / "out"),
        "--cq-dir", str(tmp_path / "cq"),
        "--cache-dir", str(cache),
    ]  # fmt: skip
    assert main(argv, commit="abc", ignored=lambda p: False) == 1
    assert "--cache-dir" in capsys.readouterr().err
    assert not cache.exists()
    assert not (tmp_path / "out" / "scores.json").exists()


def test_다른_impl_채점은_core를_안_쓰고_cost는_그대로_0이다(tmp_path, goldsets_root):
    text = (FIX / "config_ok.yaml").read_text(encoding="utf-8")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(text, encoding="utf-8")
    repo = InMemoryChunkRepository.from_jsonl("cite", CHECK_CHUNKS)
    scores = score(
        load_config(cfg_path),
        repo,
        goldsets_root,
        "abc",
        scores_dir=tmp_path / "out",
        cq_dir=tmp_path / "cq",
    ).scores
    assert scores["cost"]["external_calls"] == 0
    assert "not_extracted" not in scores["failures"]
    assert "model_calls" not in scores["cost"]
