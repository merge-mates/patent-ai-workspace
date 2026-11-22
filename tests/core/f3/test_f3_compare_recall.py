"""대비 프롬프트 스위치(compare_variant) 테스트: 끔은 지금과 같고 켬은 새 프롬프트.

프롬프트 문구는 테스트하지 않는다. 어느 파일·어느 단계(step)로 모델에 가는지만 본다.
"""

import hashlib
import json
from pathlib import Path

import pytest

from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.run import run_f3
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.transport import TransportResponse
from tests.core.f3 import scenario

# 지금 compare.md의 해시. 끔이 "지금과 같다"를 지키려고 그 파일이 바뀌면 알린다
# (바뀌면 캐시 키가 달라져 기준선 실행의 캐시가 못 쓰인다)
STANDARD_PROMPT_SHA256 = "510f215073cec92dd19439062404dedf035a66709cc570ad2a72c6ba3c3ee80a"


def _run(variant: str, answers: dict | None = None):
    config = scenario.config()
    settings = config.settings.model_copy(update={"compare_variant": variant})
    ctx, transport = scenario.context(answers)
    result = run_f3(
        scenario.oa_result(),
        scenario.MATERIALS,
        config.model_copy(update={"settings": settings}),
        ctx=ctx,
        searcher=scenario.searcher(),
        repo=scenario.REPO,
    )
    return result, transport


def _groups(prompt: str) -> list[dict]:
    """프롬프트 맨 끝 후보 JSON(구성요소별 묶음)을 읽는다."""
    return json.loads(prompt[prompt.index("\n[\n") + 1 :])


def test_기본_설정은_끔이다():
    assert load_f3_settings().compare_variant == "standard"


def test_끔이면_지금_프롬프트와_단계_이름으로_모델에_간다():
    _, transport = _run("standard")
    compares = [c for c in transport.calls if c["step"].startswith("f3.compare")]
    assert [c["step"] for c in compares] == ["f3.compare", "f3.compare"]
    path = REPO_ROOT / load_step_config("f3.compare").prompt
    assert path == REPO_ROOT / "prompts/f3/compare.md"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == STANDARD_PROMPT_SHA256
    # 끔의 후보는 예전처럼 평평한 목록이다 (구성요소 묶음·순위 칸 없음)
    flat = json.loads(compares[0]["prompt"][compares[0]["prompt"].index("\n[\n") + 1 :])
    assert all("element_no" not in c and "rank" not in c for c in flat)
    # 새 프롬프트의 내용은 끔일 때 섞이지 않는다
    recall_text = (REPO_ROOT / "prompts/f3/compare_recall.md").read_text(encoding="utf-8")
    assert recall_text.split("\n")[1] not in compares[0]["prompt"]


def test_켬이면_새_프롬프트_파일을_쓴다():
    answers = scenario.responses()
    answers["f3.compare_recall"] = answers.pop("f3.compare")
    _, transport = _run("recall", answers)
    compares = [c for c in transport.calls if c["step"].startswith("f3.compare")]
    assert [c["step"] for c in compares] == ["f3.compare_recall", "f3.compare_recall"]
    cfg = load_step_config("f3.compare_recall")
    assert cfg.prompt == "prompts/f3/compare_recall.md"
    assert Path(REPO_ROOT / cfg.prompt).is_file()
    # 모델·effort·토큰·호출 상한은 끔 단계와 같게 둔다 (프롬프트만 다른 비교)
    base = load_step_config("f3.compare")
    assert (cfg.model, cfg.effort, cfg.max_tokens, cfg.max_model_calls, cfg.max_retries) == (
        base.model,
        base.effort,
        base.max_tokens,
        base.max_model_calls,
        base.max_retries,
    )
    # recall 프롬프트 고유 구조: 후보가 구성요소 번호별 묶음으로 간다 (끔의 한 덩어리 목록이 아님)
    groups = _groups(compares[0]["prompt"])
    assert [g["element_no"] for g in groups] == [1, 2]
    assert scenario.P23 in {c["chunk_id"] for c in groups[0]["candidates"]}
    assert scenario.P31 in {c["chunk_id"] for c in groups[1]["candidates"]}


def test_켬에서_구성요소_하나에_문단_여러_개를_고르면_대비표_줄_근거로_모두_실린다():
    def pick(chunk_id, quote):
        return {"chunk_id": chunk_id, "quote": quote}

    both = {
        "element_no": 1,
        "citation": "D1",
        "judgment": "disclosed",
        "evidence": [
            pick(scenario.P23, "습도 센서는 흙에 꽂혀 습도를 잰다"),
            pick(scenario.P31, "물통은 물을 담아 둔다"),
        ],
    }
    answers = scenario.responses()
    second = answers["f3.compare"][1]
    row2 = scenario._row(2, "disclosed", (scenario.P31, "물통은 물을 담아 둔다"))
    first = TransportResponse(
        json.dumps({"claim": 1, "rows": [both, row2]}, ensure_ascii=False),
        100,
        50,
    )
    answers["f3.compare_recall"] = [first, second]
    del answers["f3.compare"]
    result, _ = _run("recall", answers)
    (table,) = result.comparisons
    row = next(r for r in table.rows if r.claim == 1 and r.element == scenario.SENSOR)
    assert {e.chunk_id for e in row.evidence} == {scenario.P23, scenario.P31}


def test_스위치_값이_틀리면_멈춘다(tmp_path):
    text = (REPO_ROOT / "config/f3.yaml").read_text(encoding="utf-8")
    bad = text.replace("compare_variant: standard", "compare_variant: no_such")
    assert bad != text
    (tmp_path / "f3.yaml").write_text(bad, encoding="utf-8")
    with pytest.raises(ModelConfigError):
        load_f3_settings(tmp_path)


def test_스위치_칸이_설정에서_빠지면_멈춘다(tmp_path):
    text = (REPO_ROOT / "config/f3.yaml").read_text(encoding="utf-8")
    kept = "\n".join(line for line in text.splitlines() if not line.startswith("compare_variant:"))
    (tmp_path / "f3.yaml").write_text(kept, encoding="utf-8")
    with pytest.raises(ModelConfigError):
        load_f3_settings(tmp_path)


def test_켬에서_구성요소_묶음은_그_구성요소_검색_순위_순이고_안_잡힌_후보는_따로_둔다():
    from tests.core.f3 import test_f3_second_search as ss

    out, calls = _run_second(second_search=False, responses=[ss.FIRST])
    groups = _groups(calls[0]["prompt"])
    by_no = {g["element_no"]: g["candidates"] for g in groups}
    # k=1: 구성요소마다 1위 문단 하나. 검색 순위 칸이 같이 간다
    assert [c["rank"] for c in by_no[1]] == [1] and [c["rank"] for c in by_no[2]] == [1]
    # 심사관 지정 문단은 모델에 순위·표시 없이 element_no null 묶음으로만 간다
    for g in groups:
        assert all("examiner" not in c for c in g["candidates"])


def test_켬에서_한_번_더_찾는_호출도_compare_recall_단계로_간다():
    from tests.core.f3 import test_f3_second_search as ss

    second = ss._answer((2, "disclosed", (ss.P40, "뚜껑 아래 수조가 있다")))
    out, calls = _run_second(second_search=True, responses=[ss.FIRST, second])
    assert [c["step"] for c in calls] == ["f3.compare_recall", "f3.compare_recall"]
    # 두 번째 호출도 구성요소별 묶음 모양이다
    assert all(g["element_no"] in (2, None) for g in _groups(calls[1]["prompt"]))


def _run_second(second_search: bool, responses: list):
    """test_f3_second_search와 같은 지어낸 사건을 recall로 돈다. (결과, 모델 호출 기록)"""
    from patent_ai.core.f3_claim_compare.compare import STEP_RECALL, compare_unit
    from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
    from patent_ai.core.f3_claim_compare.units import build_units
    from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
    from patent_ai.core.llm.transport import FakeTransport
    from tests.core.f3 import test_f3_second_search as ss

    base = load_f3_settings()
    settings = base.model_copy(
        update={
            "compare_variant": "recall",
            "second_search": second_search,
            "second_search_depth": 2,
            "search": base.search.model_copy(update={"k": 1}),
        }
    )
    inputs = F3Inputs(claims_at_oa=ss.CLAIMS, claims_status=scenario.OK, claims_document_id="d_c")
    config = F3Config(settings=settings, inputs=inputs)
    transport = FakeTransport({STEP_RECALL: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    units, _ = build_units(ss.RESULT, ss.SPLITS)
    out = compare_unit(
        units[0], ss.RESULT, ss.SPLITS, config, ctx=ctx, searcher=ss._Recorder(), repo=ss.REPO
    )
    return out, transport.calls
