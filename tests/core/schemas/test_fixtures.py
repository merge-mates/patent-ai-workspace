"""사건 1건 fixture(case_missing_citation)가 스키마 검사를 통과하고 API 예시와 겉 모양이 같은지."""

import json
import re
from pathlib import Path

import pytest

from patent_ai.core.schemas.case_materials import CaseMaterials, HeldTask
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.oa_result import OAResult, collect_evidence
from patent_ai.core.schemas.propagation import (
    ReviewItem,
    collect_review_items,
    finalize_case_materials,
)

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
            target="oa_result[oa_1].rejections[2]",
            label="42-3",
            reason="지원 안 하는 거절이유 42-3",
        ),
        ReviewItem(
            kind="missing_material",
            target="materials.missing[0]",
            label="D2 US20990000001A1 본문",
            reason="body_missing",
        ),
    ]


def test_review_items_count가_검토할_사항_수와_같다(oa, materials):
    assert materials.review_items_count == len(collect_review_items([oa], materials)) == 2


def test_6번의_review_items가_마무리_결과와_같다(oa, materials):
    # fixture는 마무리(모으기 + 순서 + 개수)를 거친 값: 빠진 자료 줄이 맨 위
    assert materials.review_items == finalize_case_materials([oa], materials).review_items
    assert len(materials.review_items) == materials.review_items_count


def test_보류와_빠진_자료가_서로_맞는다(materials):
    missing = materials.missing[0]
    assert missing.ask_upload is True
    assert materials.held_tasks == [
        HeldTask(task="f3_compare:oa_1:D2", waiting_for="D2 US20990000001A1 본문")
    ]
    assert materials.held_tasks[0].task in missing.depends_on_tasks


def test_근거에_쪽_없는_값은_없다(oa):
    evidence = collect_evidence(oa, "doc_oa_1")
    assert evidence and all(e.page is not None for e in evidence)


# ---- 화면용 네 값 사건 (f5/case_all_statuses): 화면 스크린샷 기준 자료 ----
ALL_STATUSES_DIR = ROOT / "tests" / "fixtures" / "f5" / "case_all_statuses"


@pytest.fixture
def all_oa() -> OAResult:
    return OAResult.model_validate_json((ALL_STATUSES_DIR / "oa_result.json").read_text("utf-8"))


@pytest.fixture
def all_materials() -> CaseMaterials:
    return CaseMaterials.model_validate_json(
        (ALL_STATUSES_DIR / "case_materials.json").read_text("utf-8")
    )


def test_네_값_사건이_스키마_검사를_통과한다(all_oa, all_materials):
    assert all_oa.oa_id == "oa_1"
    assert all_materials.case_id == "c_all_statuses"


def test_네_값_사건의_칸마다_정해진_status가_들어_있다(all_oa):
    # 확인됨: 출원번호
    assert all_oa.application_number.status.value == StatusValue.CONFIRMED
    assert all_oa.application_number.status.checked
    # 확인되지 않음(not_extracted): 제출기일
    assert all_oa.response_due.status.value == StatusValue.UNVERIFIED
    assert all_oa.response_due.status.reason == "not_extracted"
    # 조회 범위 내 없음: 값 하나 (어디까지 찾았는지가 있다)
    not_found = all_oa.examiner_hints.amendment_note
    assert not_found.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert not_found.status.searched_scope
    # 충돌: 발송번호, 후보 둘
    assert all_oa.dispatch_number.status.value == StatusValue.CONFLICT
    assert len(all_oa.dispatch_number.candidates) == 2
    # 날짜 칸: 값은 비우고 원문 글자만
    assert all_oa.notice_date.value is None and all_oa.notice_date.raw_text
    # 결과 status는 가장 나쁜 값(충돌)
    assert all_oa.status.value == StatusValue.CONFLICT


def test_네_값_사건에_직접_검토_거절이유_42_3이_있다(all_oa):
    rej = [r for r in all_oa.rejections if not r.supported]
    assert [r.article.value for r in rej] == ["42-3"]
    assert "needs_human_review" in [f.value for f in rej[0].flags]


def test_네_값_사건에_빠진_자료_하나와_보류가_있다(all_materials):
    assert len(all_materials.missing) == 1
    assert all_materials.missing[0].ask_upload is True
    assert [h.task for h in all_materials.held_tasks] == ["f3_compare:oa_1:D2"]


def test_네_값_사건의_review_items가_마무리_결과와_같다(all_oa, all_materials):
    # 실패: fixture의 줄이 finalize_case_materials로 다시 만든 값과 다르면
    expected = finalize_case_materials([all_oa], all_materials)
    assert all_materials.review_items == expected.review_items
    assert all_materials.review_items_count == len(expected.review_items) > 0
    kinds = {r.kind for r in all_materials.review_items}
    assert {"missing_material", "conflict", "unverified", "needs_human_review"} <= kinds
