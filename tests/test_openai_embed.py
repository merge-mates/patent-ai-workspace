import pytest

from src.retrieval.openai_embed import batches, embed_texts, load_api_key


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text

    def json(self):
        return self._p


def test_batches_split_in_order():
    assert list(batches(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]


def test_embed_texts_keeps_order_by_index_across_batches():
    calls = []

    def post(url, headers, json, timeout):
        calls.append(json["input"])
        n = len(json["input"])
        # 일부러 순서를 뒤섞어 돌려준다
        data = [{"index": i, "embedding": [float(len(json["input"][i]))]} for i in reversed(range(n))]
        return FakeResp(200, {"data": data})

    texts = ["a" * i for i in range(1, 131)]  # 130개 -> 64 + 64 + 2
    vecs = embed_texts(texts, "m", "KEY", post=post)
    assert [len(c) for c in calls] == [64, 64, 2]
    assert vecs == [[float(i)] for i in range(1, 131)]


def test_retry_then_success_and_error_message_hides_key(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [FakeResp(429), FakeResp(200, {"data": [{"index": 0, "embedding": [1.0]}]})]
    assert embed_texts(["x"], "m", "SECRETKEY", post=lambda *a, **k: seq.pop(0)) == [[1.0]]

    with pytest.raises(RuntimeError) as e:
        embed_texts(["x"], "m", "SECRETKEY", post=lambda *a, **k: FakeResp(401, text="bad"))
    assert "SECRETKEY" not in str(e.value)


def test_load_api_key(tmp_path):
    p = tmp_path / ".env"
    p.write_text('OTHER=1\nOPENAI_API_KEY="abc123"\n', encoding="utf-8")
    assert load_api_key(p) == "abc123"
    p.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_api_key(p)
