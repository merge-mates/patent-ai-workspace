"""화면 타입을 뽑을 결과 스키마의 JSON Schema를 표준 출력으로 낸다.

web/scripts/gen-types.mjs가 불러 json-schema-to-typescript로 TS 타입을 만든다.
손으로 같은 타입을 다시 쓰지 않으려는 것 (web/CLAUDE.md).

    uv run python scripts/web_schemas.py
"""

import json

from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.core.schemas.propagation import ReviewItem

# ① OA 정리, ⑥ 사건 자료·보류 목록, 검토할 사항, 원문 쪽 글자
MODELS = {
    "OAResult": OAResult,
    "CaseMaterials": CaseMaterials,
    "ReviewItem": ReviewItem,
    "PageText": PageText,
}

if __name__ == "__main__":
    # 화면은 서버 응답(직렬화된 JSON)을 받으므로 serialization 모드로 뽑는다
    out = {name: m.model_json_schema(mode="serialization") for name, m in MODELS.items()}
    print(json.dumps(out, ensure_ascii=False))
