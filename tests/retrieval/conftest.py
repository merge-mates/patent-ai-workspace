import pytest

from patent_ai.retrieval import contract


@pytest.fixture(autouse=True)
def _등록표_원래대로():
    # 테스트 안에서 등록한 가짜 구현이 다른 테스트로 새지 않게 되돌린다
    saved = dict(contract._REGISTRY)
    yield
    contract._REGISTRY.clear()
    contract._REGISTRY.update(saved)
