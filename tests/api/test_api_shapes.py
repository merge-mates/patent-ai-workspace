"""서버 응답 칸 = 화면 임시 타입 칸 (#56 T4), 그리고 openapi.yaml이 코드와 같은지.

화면 타입(web/src/types/provisional/case.ts)을 읽어 인터페이스 칸을 뽑아 서버 응답 모델의
칸과 견준다. 선택 칸(`?`)은 서버가 줘도 되고 안 줘도 되므로 필수 칸만 서버에 꼭 있어야 한다.
fixture c_*.json은 응답이 아니라 묶음이라 비교 대상이 아니다.
"""

import re
import sys
from pathlib import Path

import pytest

from patent_ai.api.main import create_app

ROOT = Path(__file__).resolve().parents[2]
CASE_TS = ROOT / "web/src/types/provisional/case.ts"

# 화면 인터페이스 이름 -> 서버 응답 모델 이름
PAIRS = {
    "CaseSummary": "CaseSummary",
    "CaseDetail": "CaseDetail",
    "OADetail": "OADetail",
    "CreatedCase": "CreatedCase",
}


def ts_keys(name: str) -> tuple[set[str], set[str]]:
    """인터페이스의 (필수 칸, 선택 칸). 맨 앞 두 칸 들여쓴 줄만 칸으로 본다."""
    src = CASE_TS.read_text(encoding="utf-8")
    m = re.search(rf"export interface {name} \{{\n(.*?)\n\}}", src, re.S)
    assert m, f"{name} 인터페이스가 case.ts에 없다"
    required, optional = set(), set()
    for line in m.group(1).split("\n"):
        k = re.match(r"  (\w+)(\??):", line)
        if k:
            (optional if k.group(2) else required).add(k.group(1))
    return required, optional


@pytest.fixture(scope="module")
def schemas():
    return create_app().openapi()["components"]["schemas"]


@pytest.mark.parametrize(("ts_name", "server_name"), PAIRS.items())
def test_서버_응답_칸이_화면_타입_칸과_같다(schemas, ts_name, server_name):
    required, optional = ts_keys(ts_name)
    server = set(schemas[server_name]["properties"])
    assert required <= server, f"화면에 필요한데 서버가 안 주는 칸: {required - server}"
    assert server <= required | optional, (
        f"서버만 주는 칸(화면 타입에 없음): {server - required - optional}"
    )


def test_OADetail의_latest_run은_화면도_null을_받는다():
    src = CASE_TS.read_text(encoding="utf-8")
    assert re.search(r"latest_run: LatestRun \| null", src)


def test_openapi_yaml은_코드에서_만든_것과_같다():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from export_openapi import OUT, render
    finally:
        sys.path.pop(0)
    assert OUT.read_text(encoding="utf-8") == render(), (
        "docs/api/openapi.yaml이 낡았다: uv run python scripts/export_openapi.py"
    )
