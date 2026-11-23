"""법령 색인 읽기: 검색기 설정이 기준선 실험(m2-i2-law-bm25-char-bigram)과 같은지."""

import yaml

from patent_ai.core.f2_legal_research import index
from patent_ai.core.f2_legal_research.run import load_f2_settings
from patent_ai.core.llm.config import REPO_ROOT


class _Repo:
    """조각 하나짜리 가짜 저장소 (설정이 넘어가는지만 본다)."""

    def has_index_version(self, corpus, version):
        return True

    def chunks(self, corpus, version, *args, **kwargs):
        return [object()]

    def close(self):
        pass


def test_검색기에_넘기는_설정이_기준선_실험과_같다(monkeypatch):
    seen = {}

    def fake_get_searcher(impl, repo, settings):
        seen.update(impl=impl, settings=settings)
        return object()

    monkeypatch.setattr(index, "open_law_repo", _Repo)
    monkeypatch.setattr(index, "InMemoryChunkRepository", lambda chunks: object())
    monkeypatch.setattr(index, "get_searcher", fake_get_searcher)
    index.load_legal_index(load_f2_settings())

    path = REPO_ROOT / "experiments/m2-i2-law-bm25-char-bigram/config.yaml"
    base = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert seen["impl"] == base["impl"]
    assert seen["settings"]["tokenizer"] == base["settings"]["tokenizer"]
    assert seen["settings"]["bm25"] == base["settings"]["bm25"]
