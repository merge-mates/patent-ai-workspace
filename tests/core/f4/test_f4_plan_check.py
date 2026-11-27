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


# ---- E 보정안 → 앱 바깥 보정 결과 (amendment_enabled false 모드 입력) ----
def test_E_보정안을_바깥_보정_결과로_옮기고_합친_곳을_찾는다():
    from patent_ai.core.f4_response_draft.plan_check import to_external

    plan = [
        {
            "claim": 1,
            "action": "amend",
            "text": (
                "영상을 받는 단계; 영상을 나누는 단계; 및 상기 나누는 단계는 경계선을 쓰는 방법."
            ),
        },
        {"claim": 2, "action": "delete", "text": ""},
        {"claim": 3, "action": "amend", "text": "제1항에 있어서, 상기 경계선은 곡선인 방법."},
    ]
    ext = to_external(OLD, plan, source="E 1번 안")
    rows = {c.claim: c for c in ext.claims}
    assert ext.source == "E 1번 안"
    assert rows[1].change == "amended" and rows[1].after == plan[0]["text"]
    assert rows[2].change == "deleted" and rows[2].merged_into == [1]
    assert rows[3].change == "amended" and rows[3].merged_into == []


def test_글이_그대로인_정정은_바깥_보정_결과에서_뺀다():
    from patent_ai.core.f4_response_draft.plan_check import to_external

    ext = to_external(OLD, [{"claim": 1, "action": "amend", "text": OLD[1]}], source="E")
    assert ext.claims == []


def test_합친_곳은_지운_항의_뿌리_독립항_가족_안에서만_찾는다():
    from patent_ai.core.f4_response_draft.plan_check import to_external

    old = {
        1: "영상을 받는 장치.",
        2: "제1항에 있어서, 경계선을 곡선으로 나누는 장치.",
        3: "영상을 받는 방법.",
        4: "제3항에 있어서, 경계선을 곡선으로 나누는 방법.",
    }
    plan = [
        {"claim": 1, "action": "amend", "text": "영상을 받고, 경계선을 곡선으로 나누는 장치."},
        {"claim": 2, "action": "delete", "text": ""},
        {"claim": 3, "action": "amend", "text": "영상을 받고, 경계선을 곡선으로 나누는 방법."},
        {"claim": 4, "action": "delete", "text": ""},
    ]
    rows = {c.claim: c for c in to_external(old, plan, source="E").claims}
    assert rows[2].merged_into == [1]  # 짝 방법 독립항(3)에도 비슷한 글이 있지만 가족이 다르다
    assert rows[4].merged_into == [3]


def test_E가_합친_곳을_주면_그것을_먼저_쓴다():
    from patent_ai.core.f4_response_draft.plan_check import to_external

    plan = [
        {"claim": 1, "action": "amend", "text": "영상을 받고 나누는 방법."},
        {"claim": 2, "action": "delete", "text": "", "merged_into": [1]},
        {"claim": 3, "action": "delete", "text": "", "merged_into": []},
    ]
    rows = {c.claim: c for c in to_external(OLD, plan, source="E").claims}
    assert rows[2].merged_into == [1]  # 글 조각으로는 못 찾지만 E가 준 값
    assert rows[3].merged_into == []  # E가 빈 목록을 주면 그냥 삭제 (어림하지 않음)
