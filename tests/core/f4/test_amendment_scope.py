"""F4 보정 범위 계산 테스트 (ADR 0005 결정 2·6, tasks.md m3-i2-scope-a task-2).

기대값은 ADR 0005 결정 2("같은 거절이유의 진보성·신규성 묶음 전부의 독립항 + 그 종속항")와
구현 계획 task-2 "테스트할 경우"에서 가져왔다. 청구항 번호 구조는 지어낸 예시다.
"""

import logging

from patent_ai.core.f4_response_draft.claim_refs import ClaimRef
from patent_ai.core.f4_response_draft.scope import amendment_scope
from patent_ai.core.schemas.common import Status
from patent_ai.core.schemas.judgment_unit import JudgmentUnit

OK = Status(value="confirmed", checked="청구항 원문 대조")


def _unit(rep: int, claims: list[int], rejection: int = 1, kind: str = "inventive_step", **kw):
    article = {"inventive_step": "29-2", "novelty": "29-1", "clarity": "42-4-2"}[kind]
    unit_kind = "single_claim" if kind == "clarity" else "independent_group"
    return JudgmentUnit(
        status=OK,
        unit_id=f"oa_1:{article}:c{rep}",
        rejection=rejection,
        rejection_kind=kind,
        unit_kind=unit_kind,
        representative_claim=rep,
        claims=claims,
        order=1,
        **kw,
    )


def _refs(deps: dict[int, list[int] | None]) -> dict[int, ClaimRef]:
    return {n: ClaimRef(claim=n, depends_on=d, head="") for n, d in deps.items()}


# 장치 독립항 1(종속 2~6) + 방법 독립항 7(종속 8~9) + 매체 독립항 10(종속 없음)
PARALLEL = _refs({1: [], 2: [1], 3: [2], 4: [1], 5: [1, 2], 6: [5], 7: [], 8: [7], 9: [8], 10: []})


def test_한_독립항_가족이면_독립항과_종속항_전부():
    u = _unit(1, [1, 2])
    s = amendment_scope(u, [u], _refs({1: [], 2: [1], 3: [2], 4: [1], 5: []}))
    assert s.claims == [1, 2, 3, 4]  # 다른 독립항 5와 그 가족은 같은 거절이유 대상이 아니라 뺀다
    assert s.targets == [1, 2]
    assert s.widened == [3, 4]


def test_같은_거절이유의_병렬_독립항_가족을_합친다():
    # 1차 실험 사전 점검: 병렬 독립항에 다른 가족 종속항 특징을 넣은 보정을 덮으려면
    # 거절이유 단위가 필요
    a, b = _unit(1, [1, 4]), _unit(7, [7])
    s = amendment_scope(b, [a, b], PARALLEL)
    assert s.claims == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert s.targets == [7]
    assert s.same_rejection_targets == [1, 4]
    assert s.widened == [2, 3, 5, 6, 8, 9]


def test_다른_거절이유의_독립항은_넣지_않는다():
    a, b = _unit(1, [1], rejection=1), _unit(7, [7], rejection=2)
    s = amendment_scope(a, [a, b], PARALLEL)
    assert 7 not in s.claims
    assert s.same_rejection_targets == []


def test_여러_항을_인용하는_항은_닿는_독립항마다_들어간다():
    refs = _refs({1: [], 2: [1], 3: [], 4: [1, 2, 3]})
    a = _unit(1, [1])
    b = _unit(3, [3], rejection=2)
    assert 4 in amendment_scope(a, [a, b], refs).claims
    assert 4 in amendment_scope(b, [a, b], refs).claims


def test_대상이_종속항뿐이면_거슬러_올라간_독립항의_가족():
    u = _unit(2, [2])
    s = amendment_scope(u, [u], PARALLEL)
    assert s.claims == [1, 2, 3, 4, 5, 6]


def test_명확성_묶음은_넓히지_않는다():
    c = _unit(3, [3], kind="clarity", read_with=[1, 2])
    i = _unit(1, [1])
    s = amendment_scope(c, [c, i], PARALLEL)
    assert s.claims == [1, 2, 3]
    assert s.widened == []


def test_명확성_묶음은_진보성_범위에_섞이지_않는다():
    c = _unit(7, [7], kind="clarity")
    i = _unit(1, [1])
    s = amendment_scope(i, [c, i], PARALLEL)
    assert 7 not in s.claims


def test_인용을_모르는_항은_범위에_넣지_않고_남긴다(caplog):
    refs = _refs({1: [], 2: [1], 3: None})
    u = _unit(1, [1])
    with caplog.at_level(logging.WARNING):
        s = amendment_scope(u, [u], refs)
    assert s.claims == [1, 2]
    assert s.unknown_refs == [3]
    assert "3" in caplog.text


def test_묶음_청구항은_인용을_몰라도_늘_범위에_든다():
    refs = _refs({1: [], 2: None})
    u = _unit(1, [1, 2])
    assert amendment_scope(u, [u], refs).claims == [1, 2]


def test_인용_관계표가_비면_묶음_청구항만(caplog):
    u = _unit(1, [1, 2])
    with caplog.at_level(logging.WARNING):
        s = amendment_scope(u, [u], {})
    assert s.claims == [1, 2]
    assert s.widened == []
    assert caplog.text
