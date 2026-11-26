"""화면 타입을 뽑을 결과 스키마의 JSON Schema를 표준 출력으로 낸다.

web/scripts/gen-types.mjs가 불러 json-schema-to-typescript로 TS 타입을 만든다.
손으로 같은 타입을 다시 쓰지 않으려는 것 (web/CLAUDE.md).

    uv run python scripts/web_schemas.py
"""

import json

from patent_ai.core.f4_response_draft.case_amendment import ExtraClaim
from patent_ai.core.f4_response_draft.plan_check import PlanIssue
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.comparison import ClarityReview, ComparisonTable
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.drafts import Drafts
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.legal_evidence import LegalEvidenceBundle
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.core.schemas.propagation import ReviewItem

# ① OA 정리, ② 판단 단위, ③ 대비표·명확성 검토, ④ 법률 근거, ⑤ 대응 방향·초안,
# ⑥ 사건 자료·보류 목록, 검토할 사항, 원문 쪽 글자
MODELS = {
    "OAResult": OAResult,
    "JudgmentUnit": JudgmentUnit,
    "ComparisonTable": ComparisonTable,
    "ClarityReview": ClarityReview,
    "LegalEvidenceBundle": LegalEvidenceBundle,
    "DirectionCandidates": DirectionCandidates,
    "Drafts": Drafts,
    "CaseMaterials": CaseMaterials,
    "ReviewItem": ReviewItem,
    "PageText": PageText,
    # 사건 단위 보정안의 코드 검사 표시 (초안 API amendment_checks, 이 브랜치)
    "PlanIssue": PlanIssue,
    "ExtraClaim": ExtraClaim,
}


def _all_required(node: object) -> None:
    """직렬화한 JSON에는 기본값 칸도 늘 들어 있으므로 객체의 모든 칸을 필수로 표시한다.

    (core/schemas/ 설정은 고치지 않고 뽑은 스키마만 바꾼다. 그래야 TS에서 `?`가 안 붙는다)
    """
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
        for v in node.values():
            _all_required(v)
    elif isinstance(node, list):
        for v in node:
            _all_required(v)


if __name__ == "__main__":
    # 화면은 서버 응답(직렬화된 JSON)을 받으므로 serialization 모드로 뽑는다
    out = {name: m.model_json_schema(mode="serialization") for name, m in MODELS.items()}
    _all_required(out)
    print(json.dumps(out, ensure_ascii=False))
