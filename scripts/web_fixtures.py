"""화면 mock용 fixture를 만든다: git에 있는 가짜 통지서 + 기록된 모델 응답으로 read_oa를 돌린다.

네트워크·API 키 없이 돈다 (FakeTransport). 결과는 web/src/api/fixtures/ 에 JSON으로 쓴다.
실제 사건 JSON은 여기서 다루지 않는다 (시연용은 git 밖 web/.demo/).

    uv run python scripts/web_fixtures.py
"""

import json
from pathlib import Path

from patent_ai.core.f1_oa_reader.case_grouping import GroupedMaterial, build_case_materials
from patent_ai.core.f1_oa_reader.read_oa import read_oa
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.case_materials import CaseMaterials, LookupResult
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult

ROOT = Path(__file__).resolve().parents[1]
F1 = ROOT / "tests" / "fixtures" / "f1"
ALL_STATUSES = ROOT / "tests" / "fixtures" / "f5" / "case_all_statuses"
OUT = ROOT / "web" / "src" / "api" / "fixtures"
STEP = "f1.read_oa"

# 사건 셋. 칸: 사건 ID·이름·마지막으로 연 때, OA ID, 문서 ID, 통지서 fixture, 기록된 응답,
# 번호 바꾸기, 받은 인용문헌(키 꼴), 못 받은 인용문헌의 이유.
# 번호 바꾸기는 같은 가짜 통지서를 다른 사건처럼 보이게 쪽 글자와 응답에 똑같이 적용한다.
CASES = [
    {
        "case_id": "c_1",
        "case_name": "가상의 영상 처리 장치",
        "last_opened_at": "2099-02-12T09:30:00",
        "oa_id": "oa_1",
        "document_id": "d_1",
        "notice": "notice_claim_rows",
        "answer": "claim_rows",
        "replace": {},
        "received": {"KR20990000011A"},
        "failures": {},
    },
    {
        "case_id": "c_2",
        "case_name": "가상의 센서 장치",
        "last_opened_at": "2099-01-28T14:05:00",
        "oa_id": "oa_2",
        "document_id": "d_2",
        "notice": "notice_unsupported",
        "answer": "unsupported",
        "replace": {},
        "received": {"KR20990000001A"},
        "failures": {},
    },
    {
        "case_id": "c_3",
        "case_name": "가상의 온도 조절 장치",
        "last_opened_at": "2099-01-30T17:40:00",
        "oa_id": "oa_3",
        "document_id": "d_3",
        "notice": "notice_final",
        "answer": "conflict",
        # 최후거절이유통지 예시: 사건 2와 겹치지 않게 번호·이름을 바꾼다
        "replace": {
            "10-2099-0000001": "10-2099-0000003",
            "9-5-2099-000000001": "9-5-2099-000000003",
            "가상의 센서 장치": "가상의 온도 조절 장치",
        },
        "received": set(),
        "failures": {"KR20990000003A": LookupResult.BODY_MISSING},
    },
    {
        # 네 status 값이 다 있는 지어낸 사건. 모델 없이 fixture 폴더의 값을 그대로 쓴다
        "case_id": "c_4",
        "case_name": "가상의 상태 표시 시연 장치",
        "last_opened_at": "2099-02-02T10:00:00",
        "oa_id": "oa_4",
        "fixture_dir": ALL_STATUSES,
    },
]


def _swap(text: str, pairs: dict[str, str]) -> str:
    for old, new in pairs.items():
        text = text.replace(old, new)
    return text


def _pages(name: str, document_id: str, pairs: dict[str, str]) -> PageText:
    raw = _swap((F1 / f"{name}.pages.json").read_text("utf-8"), pairs)
    data = json.loads(raw)
    data["document_id"] = document_id
    return PageText.model_validate(data)


def _from_fixture_dir(c: dict) -> dict:
    """이미 만들어 둔 fixture 폴더(oa_result·case_materials·pages)를 묶음으로 옮긴다."""
    d = c["fixture_dir"]
    oa = OAResult.model_validate_json((d / "oa_result.json").read_text("utf-8"))
    materials = CaseMaterials.model_validate_json((d / "case_materials.json").read_text("utf-8"))
    # 서버는 ⑥의 case_id가 사건 id와 같아야 한다 (CaseRecord). fixture 폴더 이름 대신 사건 id로
    materials = CaseMaterials.model_validate(materials.model_dump() | {"case_id": c["case_id"]})
    pages = PageText.model_validate_json((d / "pages.json").read_text("utf-8"))
    # None(마무리 안 한 ⑥)은 빈 목록으로 바꾸지 않는다: "0건"처럼 보이면 안 된다
    review = materials.review_items
    return {
        "case_id": c["case_id"],
        "case_name": c["case_name"],
        "last_opened_at": c["last_opened_at"],
        "oa_id": c["oa_id"],
        "run_id": f"r_{c['oa_id']}",  # 다른 사건과 같은 꼴
        "oa_result": oa.model_dump(mode="json"),
        "materials": materials.model_dump(mode="json"),
        "review_items": None if review is None else [r.model_dump(mode="json") for r in review],
        "document": pages.model_dump(mode="json"),
    }


def _run_one(c: dict) -> dict:
    if "fixture_dir" in c:
        return _from_fixture_dir(c)
    pairs = c["replace"]
    pages = _pages(c["notice"], c["document_id"], pairs)
    answer = _swap((F1 / "llm" / f"{c['answer']}.json").read_text("utf-8"), pairs)
    # 기록된 응답 하나를 가짜 전송층으로 돌려준다 (모델 호출 없음)
    transport = FakeTransport({STEP: TransportResponse(answer, 100, 50)})
    run_id = f"r_{c['oa_id']}"
    ctx = RunContext(
        run_id=run_id, budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    oa = read_oa(pages, c["document_id"], c["oa_id"], run_id, ctx=ctx)

    # 사건 자료: 통지서 한 건 + 인용문헌 조회 결과
    grouped = [
        GroupedMaterial(
            document_id=c["document_id"],
            kind="oa",
            source="uploaded",
            application_number=oa.application_number,
            doc_number=oa.dispatch_number,
            key=f"oa:{oa.dispatch_number.value}",
            status=Status(value=StatusValue.CONFIRMED, checked="출원번호 대조"),
        )
    ]
    materials = build_case_materials(
        c["case_id"], grouped, [oa], c["received"], lookup_failures=c["failures"]
    )
    # ⑥에 이미 담긴 목록을 그대로 쓴다 (따로 모으지 않는다)
    review = materials.review_items  # None(모름)은 빈 목록으로 바꾸지 않는다
    return {
        # 사건 이름·마지막으로 연 때는 사건 목록 응답(서버 #56)에 들어갈 값의 가짜
        "case_id": c["case_id"],
        "case_name": c["case_name"],
        "last_opened_at": c["last_opened_at"],
        "oa_id": c["oa_id"],
        "run_id": run_id,
        "oa_result": oa.model_dump(mode="json"),
        "materials": materials.model_dump(mode="json"),
        "review_items": None if review is None else [r.model_dump(mode="json") for r in review],
        "document": pages.model_dump(mode="json"),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for c in CASES:
        bundle = _run_one(c)
        path = OUT / f"{c['case_id']}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(
            f"{path.relative_to(ROOT)}: 거절이유 {len(bundle['oa_result']['rejections'])}개, "
            f"검토할 사항 {len(bundle['review_items'])}건"
        )


if __name__ == "__main__":
    main()
