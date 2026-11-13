import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import embed_openai  # noqa: E402


def _exp(tmp_path, split="dev"):
    f = tmp_path / "exp.json"
    f.write_text(json.dumps({"meta": {"model": "gm", "prompt_version": "v1", "split": split},
                             "items": [{"id": "D01", "question": "q1", "query": "q1\na, b"},
                                       {"id": "D02", "question": "q2", "query": "q2\nc"}]}), encoding="utf-8")
    return f


def test_expanded_embeds_query_text_in_item_order_and_records_source(tmp_path, monkeypatch):
    monkeypatch.setattr(embed_openai, "load_api_key", lambda: "KEY")
    seen = {}

    def fake(texts, model, key):
        seen["texts"] = texts
        return [[1.0, 0.0], [0.0, 1.0]]

    f = _exp(tmp_path)
    assert embed_openai.main(["--what", "expanded", "--expansions", str(f), "--out-dir", str(tmp_path)], embed=fake) == 0
    assert seen["texts"] == ["q1\na, b", "q2\nc"]
    out = next(tmp_path.glob("emb_*_expanded_*.json"))
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["ids"] == ["D01", "D02"] and d["meta"]["what"] == "expanded"
    assert d["meta"]["expansion"] == {"model": "gm", "prompt_version": "v1"}
    assert "KEY" not in out.read_text(encoding="utf-8")


def test_expanded_requires_file_and_blocks_holdout(tmp_path):
    with pytest.raises(SystemExit):
        embed_openai.main(["--what", "expanded"])
    with pytest.raises(SystemExit):
        embed_openai.main(["--what", "expanded", "--expansions", str(_exp(tmp_path, "holdout")), "--dry-run"])


def test_expanded_dry_run_makes_no_call(tmp_path):
    def boom(*a, **k):
        raise AssertionError("호출 금지")

    f = _exp(tmp_path)
    assert embed_openai.main(["--what", "expanded", "--expansions", str(f), "--dry-run"], embed=boom) == 0
