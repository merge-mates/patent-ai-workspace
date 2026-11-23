"""F3·F4 결과 저장·다시 읽기 메모리 구현 (이슈 #191 T2)."""

import pytest

from patent_ai.core.cases.step_results import (
    DuplicateStepResult,
    InMemoryStepResultStore,
    kind_of,
)
from patent_ai.core.f2_legal_research.run import F2Result
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f4_response_draft.result import F4Output
from tests.core.run_case_fakes import real_outcome


@pytest.fixture
def outcome(tmp_path, monkeypatch):
    return real_outcome(tmp_path, monkeypatch)


def test_step_results_F3_F4를_저장하고_다시_읽으면_같은_객체(outcome):
    store = InMemoryStepResultStore()
    f3, f4 = outcome.results["run_f3"], outcome.results["run_f4"]
    store.save_step_result("oa_1", "r_1", f3)
    store.save_step_result("oa_1", "r_1", f4)

    got3, got4 = store.step_result("r_1", "f3"), store.step_result("r_1", "f4")
    assert isinstance(got3, F3Result) and got3 == f3
    assert isinstance(got4, F4Output) and got4 == f4
    # 판단 단위·대비표·명확성 검토, 방향 후보·초안이 비지 않은 채 왕복한다
    assert got3.units and got3.comparisons and got3.clarity_reviews
    assert got4.directions and got4.drafts is not None


def test_step_results_없는_실행_단계는_None(outcome):
    store = InMemoryStepResultStore()
    store.save_step_result("oa_1", "r_1", outcome.results["run_f3"])
    assert store.step_result("r_1", "f4") is None  # F4는 저장 안 함 (넘겼거나 실패)
    assert store.step_result("r_2", "f3") is None  # 다른 실행


def test_step_results_같은_실행_같은_단계를_두_번_저장하면_거부(outcome):
    store = InMemoryStepResultStore()
    store.save_step_result("oa_1", "r_1", outcome.results["run_f3"])
    with pytest.raises(DuplicateStepResult):
        store.save_step_result("oa_1", "r_1", outcome.results["run_f3"])


def test_step_results_F2_F3_F4가_아닌_객체는_TypeError(outcome):
    with pytest.raises(TypeError):
        kind_of(outcome.results["read_oa"])


def test_step_results_F2_법률_근거도_저장하고_다시_읽으면_같은_객체(outcome):
    store = InMemoryStepResultStore()
    f2 = outcome.results["run_f2"]
    assert kind_of(f2) == "f2"
    store.save_step_result("oa_1", "r_1", f2)
    got = store.step_result("r_1", "f2")
    assert isinstance(got, F2Result) and got == f2
    assert got.bundles and got.bundles[0].claims[0].sources[0].evidence.chunk_id


def test_step_results_update는_바꾼_값으로_덮고_다시_읽으면_그_값(outcome):
    # 사람이 초안을 고칠 때 (#304): 같은 실행·같은 단계 줄을 바꾼다
    store = InMemoryStepResultStore()
    store.save_step_result("oa_1", "r_1", outcome.results["run_f4"])
    new = store.update_step_result(
        "r_1", "f4", lambda b: b.model_copy(update={"held_units": ["u_x"]})
    )
    assert new.held_units == ["u_x"]
    assert store.step_result("r_1", "f4").held_units == ["u_x"]
    assert store.update_step_result("r_2", "f4", lambda b: b) is None  # 줄 없음


def test_step_results_update에서_예외가_나면_아무것도_바꾸지_않는다(outcome):
    store = InMemoryStepResultStore()
    f4, f3 = outcome.results["run_f4"], outcome.results["run_f3"]
    store.save_step_result("oa_1", "r_1", f4)

    def boom(b):
        raise ValueError("안 됨")

    with pytest.raises(ValueError):
        store.update_step_result("r_1", "f4", boom)
    with pytest.raises(TypeError):
        store.update_step_result("r_1", "f4", lambda b: f3)  # 다른 단계 결과로 못 덮음
    assert store.step_result("r_1", "f4") == f4
