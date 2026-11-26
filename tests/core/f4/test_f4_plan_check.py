"""사건 단위 보정안(E) 코드 검사 테스트. 모델 호출 없음.

기대값은 합친 흐름 개선 목록 6번(E 보정안도 앱 안전장치를 거치게)에서 가져왔다:
지운 항을 아직 인용하는 남은 항, 명세서·원래 청구항에 없는 새 문구를 표시만 한다 (적법성 판단 아님).
"""

from patent_ai.core.f4_response_draft.plan_check import check_plan

OLD = {
    1: "영상을 받는 단계; 및 영상을 나누는 단계를 포함하는 방법.",
    2: "제1항에 있어서, 상기 나누는 단계는 경계선을 쓰는 방법.",
    3: "제2항에 있어서, 상기 경계선은 곡선인 방법.",
}
SPEC = "【0010】 경계선은 곡선 또는 선분일 수 있다. 【0011】 거리맵을 만들어 관심 영역을 정한다."


def test_지운_항을_아직_인용하는_남은_항을_찾는다():
    plan = [{"claim": 2, "action": "delete", "text": ""}]
    found = check_plan(OLD, plan, SPEC)
    assert [(x.kind, x.claim, x.detail) for x in found] == [("dangling_reference", 3, "2")]


def test_인용_번호를_고친_항은_표시하지_않는다():
    plan = [
        {"claim": 2, "action": "delete", "text": ""},
        {"claim": 3, "action": "amend", "text": "제1항에 있어서, 상기 경계선은 곡선인 방법."},
    ]
    assert check_plan(OLD, plan, SPEC) == []


def test_명세서와_원래_청구항에_없는_새_문구만_표시한다():
    text = (
        "영상을 받는 단계; 거리맵을 만들어 관심 영역을 정하는 단계; "
        "및 무지개색으로 칠하는 단계를 포함하는 방법."
    )
    found = check_plan(OLD, [{"claim": 1, "action": "amend", "text": text}], SPEC)
    assert [(x.kind, x.claim) for x in found] == [("not_in_source", 1)]
    assert "무지개색" in found[0].detail


def test_짧은_조각은_어디든_맞아_보지_않는다():
    text = "영상을 받는 단계; 및 영상을 나누는 단계를 포함하는 방법임."
    assert check_plan(OLD, [{"claim": 1, "action": "amend", "text": text}], SPEC) == []


def test_인용_머리말은_새_문구로_보지_않는다():
    text = "제 1 항 또는 제 2 항에 있어서, 상기 경계선은 곡선인 방법."
    assert check_plan(OLD, [{"claim": 3, "action": "amend", "text": text}], SPEC) == []
