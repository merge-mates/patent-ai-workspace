"""화면 mock fixture(web/src/api/fixtures/)가 지금 core 코드로 다시 뽑은 것과 같은지 본다.

core/schemas/나 read_oa가 바뀌었는데 fixture를 다시 뽑지 않으면 화면이 옛 모양으로 조용히 남는다.
다르면 `cd web && npm run gen:fixtures`로 다시 뽑는다. 네트워크·키 없이 돈다 (가짜 응답).
"""

import json

import pytest

from scripts import web_fixtures


@pytest.mark.parametrize("case", web_fixtures.CASES, ids=lambda c: c["case_id"])
def test_커밋된_fixture가_다시_뽑은_것과_같다(case):
    committed = json.loads((web_fixtures.OUT / f"{case['case_id']}.json").read_text("utf-8"))
    # 파일로 쓸 때와 같게 JSON을 한 번 거쳐 비교한다 (집합 등 파이썬 값이 섞이지 않게)
    regenerated = json.loads(json.dumps(web_fixtures._run_one(case), ensure_ascii=False))
    assert regenerated == committed
