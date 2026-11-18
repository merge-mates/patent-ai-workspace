"""사건 1건 fixture(case_missing_citation)가 스키마 검사를 통과하고 API 예시와 겉 모양이 같은지."""

import json
import re
from pathlib import Path

import pytest

from patent_ai.core.schemas.case_materials import CaseMaterials, HeldTask
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.oa_result import OAResult, collect_evidence
from patent_ai.core.schemas.propagation import ReviewItem, collect_review_items

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "case_missing_citation"
API_DOC = ROOT / "docs" / "api" / "README.md"


@pytest.fixture
def oa() -> OAResult:
    return OAResult.model_validate_json((FIXTURE_DIR / "oa_result.json").read_text("utf-8"))


@pytest.fixture
def materials() -> CaseMaterials:
    return CaseMaterials.model_validate_json(
        (FIXTURE_DIR / "case_materials.json").read_text("utf-8")
    )


def _api_example_keys() -> set[str]:
    """api/README.md 5절 `GET /oas/{oa_id}/oa-result` 예시 JSON 블록의 겉 키."""
    text = API_DOC.read_text("utf-8")
    section = text
    # 5절 안에서 "결과 (`GET /oas/{oa_id}/oa-result`)" 바로 뒤 json 블록
    m = re.search(r"결과 \(`GET /oas/\{oa_id\}/oa-result`\).*?```json\n(.*?)\n```", section, re.S)
    assert m, "api/README.md에서 oa-result 예시 블록을 못 찾음"
    return set(json.loads(m.group(1)))


def test_fixture가_스키마로_읽힌다(oa, materials):
    assert oa.oa_id == "oa_1"
    assert len(oa.rejections) == 3
    assert materials.case_id == "c_1"


def test_응답_겉_키가_api_명세_예시와_같다(oa):
    response = {"oa_id": oa.oa_id, "run_id": "r_1", "status": oa.status.value, "result": oa}
    assert set(response) == _api_example_keys() == {"oa_id", "run_id", "status", "result"}


def test_응답_모양_fixture의_바깥_status는_result_status와_같다(oa):
    # 화면 목 응답에도 쓰는 파일: {oa_id, run_id, status, result}
    response = json.loads((FIXTURE_DIR / "oa_result_response.json").read_text("utf-8"))
    assert set(response) == _api_example_keys()
    assert response["status"] == response["result"]["status"]["value"]
    assert OAResult.model_validate(response["result"]) == oa
    # 지원 안 하는 42조 3항은 빼고 모으므로 모든 값이 확인된 이 사건은 confirmed
    assert oa.status.value == StatusValue.CONFIRMED


def test_검토할_사항은_빠진_인용문헌_하나와_직접_검토_하나(oa, materials):
    items = collect_review_items([oa], materials)
    assert items == [
        ReviewItem(
            kind="needs_human_review",
            target="oa_result.rejections[2]",
            label="42-3",
            reason="지원 안 하는 거절이유 42-3",
        ),
        ReviewItem(
            kind="missing_material",
            target="materials.missing[0]",
            label="US 2099/0000001 본문",
            reason="body_missing",
        ),
    ]


def test_review_items_count가_검토할_사항_수와_같다(oa, materials):
    assert materials.review_items_count == len(collect_review_items([oa], materials)) == 2


def test_보류와_빠진_자료가_서로_맞는다(materials):
    missing = materials.missing[0]
    assert missing.ask_upload is True
    assert materials.held_tasks == [
        HeldTask(task="F3 대비: US 2099/0000001", waiting_for="US 2099/0000001 본문")
    ]
    assert materials.held_tasks[0].task in missing.depends_on_tasks


def test_근거에_쪽_없는_값은_없다(oa):
    evidence = collect_evidence(oa, "doc_oa_1")
    assert evidence and all(e.page is not None for e in evidence)
