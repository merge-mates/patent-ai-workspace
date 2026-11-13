import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import expand_queries  # noqa: E402


def test_holdout_requires_final_flag():
    with pytest.raises(SystemExit):
        expand_queries.main(["--model", "m", "--split", "holdout", "--dry-run"])


def test_dry_run_makes_no_call_and_prints_prompt(capsys):
    def boom(*a, **k):
        raise AssertionError("API 호출 금지")

    assert expand_queries.main(["--model", "m", "--dry-run"], expand=boom) == 0
    out = capsys.readouterr().out
    assert "질문 32개" in out and "조문 번호" in out


def test_run_writes_file_with_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(expand_queries, "load_api_key", lambda: "KEY")
    calls = []

    def fake(question, model, key):
        calls.append(question)
        return "침해 금지 청구, 제126조" if len(calls) == 1 else "공동출원"

    assert expand_queries.main(["--model", "m", "--out-dir", str(tmp_path)], expand=fake) == 0
    f = next(tmp_path.glob("expansions_m_dev_*.json"))
    d = json.loads(f.read_text(encoding="utf-8"))
    assert d["meta"]["n"] == 32 and d["meta"]["prompt_version"] == "v1"
    first = d["items"][0]
    assert first["terms"] == ["침해 금지 청구"] and first["raw_had_article_number"] is True
    assert first["query"] == first["question"] + "\n침해 금지 청구"
    assert "KEY" not in f.read_text(encoding="utf-8")
