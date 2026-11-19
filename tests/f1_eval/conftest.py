"""F1 채점 테스트 fixture.

도우미 본체는 f1_oa_builder.py (다른 폴더 conftest와 모듈 이름이 겹치지 않게).
"""

import pytest
from f1_oa_builder import build_oa


@pytest.fixture
def make_oa():
    return build_oa
