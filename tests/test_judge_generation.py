import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("judge_generation", Path("scripts/judge_generation.py"))
jg = importlib.util.module_from_spec(spec)
sys.modules["judge_generation"] = jg
spec.loader.exec_module(jg)

GOOD = {"faithfulness": 5, "accuracy": 4, "completeness": 5, "status_ok": True, "unsupported": [], "comment": "ok"}


def make_files(tmp_path, questions="data/eval/questions_d2_dev.jsonl"):
    cache = {"meta": {}, "items": {"N01": {"evidence": [{"tag": "E1", "article_id": "특허법#제30조", "label": "특허법 제30조",
                                                         "text": "근거 본문", "truncated": False}]}}}
    (tmp_path / "cache.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    res = {"question": "질문?", "status": "answered", "answer": "답", "evidence": [{"tag": "E1", "article_id": "특허법#제30조", "label": "특허법 제30조"}]}
    noans = {"question": "무관?", "status": "no_basis", "answer": "근거 없음", "evidence": []}
    data = {"config": {"questions": questions, "retrieval_cache": str(tmp_path / "cache.json"),
                       "generation_model": "claude-sonnet-5-5", "prompt_version": "v3"},
            "answerable": [{"id": "N01", "gold": ["특허법#제30조"], "result": res}],
            "noanswer": [{"id": "N26", "gold": [], "result": noans}]}
    art = {"chunk_id": "특허법#제30조", "text": "정답 본문", "metadata": {"law_name": "특허법", "label": "제30조", "law_effective_date": "20251111", "law_mst": "1"}}
    (tmp_path / "articles.jsonl").write_text(json.dumps(art, ensure_ascii=False) + "\n", encoding="utf-8")  # 로컬 데이터에 기대지 않는다
    p = tmp_path / "gen_x.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_judge_item_passes_cached_evidence_and_gold_text(tmp_path):
    seen = {}

    def fake(question, evidence, gold, status, answer, model, key):
        seen.update(evidence=evidence, gold=gold, status=status)
        return GOOD
    item = {"id": "N01", "gold": ["특허법#제30조"], "result": {"question": "q", "status": "answered", "answer": "a",
            "evidence": [{"article_id": "특허법#제30조", "label": "특허법 제30조"}]}}
    articles = {"특허법#제30조": {"chunk_id": "특허법#제30조", "text": "정답 본문", "metadata": {"law_name": "특허법", "label": "제30조", "law_effective_date": "20251111", "law_mst": "1"}}}
    row = jg.judge_item(item, "answerable", {"특허법#제30조": "근거 본문"}, articles, "claude-opus-5-5", "k", fake)
    assert seen["evidence"] == [("특허법 제30조", "근거 본문")] and seen["gold"][0][1] == "정답 본문"
    assert row["judgment"] == GOOD and row["kind"] == "answerable"


def test_judge_item_turns_exception_into_error_without_key(tmp_path):
    def boom(*a):
        raise RuntimeError("HTTP 401 sk-ant-SECRET")
    item = {"id": "N01", "gold": [], "result": {"question": "q", "status": "answered", "answer": "a", "evidence": []}}
    row = jg.judge_item(item, "answerable", {}, {}, "m", "k", boom)
    assert "error" in row["judgment"] and "SECRET" not in json.dumps(row)


def test_main_refuses_sealed_without_flag(tmp_path):
    p = make_files(tmp_path, questions="data/eval/questions_d2_sealed.jsonl")
    with pytest.raises(SystemExit):
        jg.main(["--results", str(p), "--out-dir", str(tmp_path)], judge_fn=lambda *a: GOOD, key="k")


def test_main_writes_new_file_with_summary_and_cost(tmp_path, capsys):
    p = make_files(tmp_path)

    def fake(question, evidence, gold, status, answer, model, key):
        from src.retrieval import usage
        usage.record("judge", model, 1000, 500)
        return GOOD
    assert jg.main(["--results", str(p), "--out-dir", str(tmp_path), "--workers", "1", "--article-corpus", str(tmp_path / "articles.jsonl")], judge_fn=fake, key="SECRET-KEY") == 0
    out = next(tmp_path.glob("judge_claude-opus-5-5_gen_x_*.json"))
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["summary"]["n"] == 2 and d["usage"]["input_tokens"] == 2000
    assert d["cost_usd"] == pytest.approx(2000 / 1e6 * 4 + 1000 / 1e6 * 20)
    assert "SECRET-KEY" not in out.read_text(encoding="utf-8")
