"""F3 한 바퀴 테스트용 지어낸 사건 하나: 진보성(청구항 1·2, D1 + 일본 문헌 D2) + 명확성(청구항 2).

run_f3 테스트와 도구 등록 테스트가 같이 쓴다. 진짜 사건 글자 없음.
"""

import functools
import json

from patent_ai.core.f3_claim_compare.compare import make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.document import Page, PageText
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import OK, citation, claim_row, oa, paragraph, rejection

D1 = "KR20990000001A"
SENSOR, TANK, MODULE = "흙의 습도를 재는 습도 센서", "물을 담는 물통", "상기 제어 모듈"
CLAIMS = {
    1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분.",
    2: f"제1항에 있어서, {MODULE}을 더 포함하는 화분.",
}
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
]
P23, P31 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})
SPEC = PageText(
    document_id="d_spec",
    status=OK,
    pages=[Page(page=1, status=OK, text="【0016】 제어 모듈은 밸브를 여닫는 회로 기판을 말한다.")],
)
MATERIALS = CaseMaterials(case_id="case_1")


def embed(query: str) -> list[float]:
    return [1.0, 0.0] if "센서" in query else [0.0, 1.0]


@functools.cache
def searcher():
    return make_searcher(load_f3_settings(), REPO, embed)


def oa_result(claims=(1, 2)):
    """거절이유 1 진보성(D1 + 일본 D2), 2 명확성(청구항 2), 3 지원 안 하는 조문."""
    cited = [citation("D1", D1), citation("D2", "JP2099000001A", country="JP")]
    return oa(
        [
            rejection(1, "29-2", list(claims), cited),
            rejection(2, "42-4-2", [2]),
            rejection(3, "45", [1]),
        ],
        [claim_row(2, 2, clarity_terms=[MODULE])],
    )


def config(claims_status=OK) -> F3Config:
    inputs = F3Inputs(
        claims_at_oa=CLAIMS, claims_status=claims_status, claims_document_id="d_claims", spec=SPEC
    )
    # 가짜 응답 개수는 한 번만 찾기 기준이라 끔으로 고정한다
    # (한 번 더 찾기는 test_f3_second_search.py가 본다)
    settings = load_f3_settings().model_copy(update={"second_search": False})
    return F3Config(settings=settings, inputs=inputs)


def _text(body: dict) -> TransportResponse:
    return TransportResponse(json.dumps(body, ensure_ascii=False), 100, 50)


def _split(claim, elements, depends_on=(), quote=None):
    return _text(
        {
            "claim": claim,
            "depends_on": list(depends_on),
            "depends_on_quote": quote,
            "elements": [{"text": t} for t in elements],
        }
    )


def _row(no, judgment, *evidence):
    picks = [{"chunk_id": c, "quote": q} for c, q in evidence]
    return {"element_no": no, "citation": "D1", "judgment": judgment, "evidence": picks}


def responses() -> dict:
    """단계마다 차례로 낼 가짜 응답."""
    return {
        "f3.split_elements": [
            _split(1, [SENSOR, TANK]),
            _split(2, [MODULE], [1], "제1항에 있어서"),
        ],
        "f3.compare": [
            _text(
                {
                    "claim": 1,
                    "rows": [
                        _row(1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
                        _row(2, "disclosed", (P31, "물통은 물을 담아 둔다")),
                    ],
                }
            ),
            _text({"claim": 2, "rows": [_row(1, "difference_candidate")]}),
        ],
        # 진보성 차이점(청구항 2 제어 모듈)의 효과 문장은 명세서에 없다고 답한다 (빈 목록)
        "f3.effect": [_text({"effects": []})],
        "f3.clarity": [
            _text(
                {
                    "claim": 2,
                    "terms": [
                        {
                            "term": MODULE,
                            "issue_type": "no_antecedent",
                            "note": "청구항 1에 제어 모듈이 나오지 않음",
                            "definition": None,
                        }
                    ],
                }
            )
        ],
    }


def context(answers: dict | None = None) -> tuple[RunContext, FakeTransport]:
    transport = FakeTransport(responses() if answers is None else answers)
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return ctx, transport
