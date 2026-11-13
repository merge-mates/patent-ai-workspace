import pytest

from src.rag.evidence import build_evidence
from src.rag.settings import load_key


def test_build_evidence_tags_labels_and_truncation():
    texts = {"특허법#제29조": "가" * 5000, "특허법 시행령#제5조": "짧은 본문"}
    ev = build_evidence(["특허법#제29조", "특허법 시행령#제5조"], texts, n=5, max_chars=4000)
    assert [e.tag for e in ev] == ["E1", "E2"]
    assert ev[0].label == "특허법 제29조" and ev[1].label == "특허법 시행령 제5조"
    assert len(ev[0].text) == 4000 and ev[0].truncated is True
    assert ev[1].text == "짧은 본문" and ev[1].truncated is False


def test_build_evidence_skips_duplicates_and_handles_fewer_than_n():
    texts = {"A#제1조": "a", "A#제2조": "b"}
    ev = build_evidence(["A#제1조", "A#제1조", "A#제2조"], texts, n=5)
    assert [e.article_id for e in ev] == ["A#제1조", "A#제2조"]
    assert [e.tag for e in ev] == ["E1", "E2"]


def test_build_evidence_stops_at_n():
    texts = {f"A#제{i}조": "x" for i in range(1, 9)}
    assert len(build_evidence(list(texts), texts, n=5)) == 5


def test_load_key_reads_env_and_error_hides_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A=secret\nB="quoted"\n', encoding="utf-8")
    assert load_key("A", env) == "secret"
    assert load_key("B", env) == "quoted"
    with pytest.raises(RuntimeError) as e:
        load_key("MISSING", env)
    assert "secret" not in str(e.value) and "MISSING" in str(e.value)


def test_build_evidence_with_zero_n_returns_nothing():
    assert build_evidence(["A#제1조"], {"A#제1조": "x"}, n=0) == []
