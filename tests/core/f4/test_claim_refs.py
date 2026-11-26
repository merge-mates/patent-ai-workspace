"""F4 인용 관계표 테스트 (ADR 0005 결정 1, tasks.md m3-i2-scope-a task-1).

기대값은 ADR 0005 결정 1과 구현 계획 task-1의 "테스트할 경우"에서 가져왔다.
청구항 글자는 지어낸 짧은 예시다 (사건 원문 아님).
"""

import logging

from patent_ai.core.f4_response_draft.claim_refs import claim_refs
from patent_ai.core.f4_response_draft.inputs import ClaimText


def _texts(*pairs: tuple[int, str]) -> list[ClaimText]:
    return [ClaimText(claim=n, text=t, document_id="doc") for n, t in pairs]


def _deps(*pairs):
    return {n: r.depends_on for n, r in claim_refs(_texts(*pairs)).items()}


def test_독립항은_빈_목록이고_종속항은_인용한_앞_항():
    got = _deps(
        (1, "입력부; 및 처리부를 포함하는 장치."),
        (2, "제1항에 있어서, 상기 처리부는 신경망인 장치."),
        (3, "제 2 항에 있어서, 상기 신경망은 합성곱 신경망인 장치."),
    )
    assert got == {1: [], 2: [1], 3: [2]}


def test_청구항_N_꼴도_읽는다():
    assert _deps((1, "방법."), (2, "청구항 1에 있어서, 단계를 더 포함하는 방법."))[2] == [1]


def test_또는과_범위를_모두_펼친다():
    got = _deps(
        (1, "장치."),
        (2, "제1항에 있어서, 장치."),
        (3, "제1항 또는 제2항에 있어서, 장치."),
        (4, "제1항 내지 제3항 중 어느 한 항에 따른 장치를 포함하는 시스템."),
    )
    assert got[3] == [1, 2]
    assert got[4] == [1, 2, 3]


def test_번호_없는_전제부는_독립항이다():
    # "…방법에 있어서"처럼 전제부를 쓴 독립항 (tune 점검에서 처음 규칙이 못 읽음으로 낸 꼴)
    assert _deps((1, "영상을 분석하는 방법에 있어서, 영상을 받는 단계를 포함하는 방법."))[1] == []


def test_자기보다_뒤_번호는_인용으로_보지_않는다():
    assert _deps((1, "장치."), (2, "제3항에 있어서, 장치."), (3, "장치."))[2] is None


def test_항을_가리키는데_번호를_못_읽으면_확인되지_않음과_경고(caplog):
    with caplog.at_level(logging.WARNING):
        got = _deps((1, "장치."), (2, "앞의 어느 한 항에 있어서, 장치."))
    assert got[2] is None
    assert "2" in caplog.text


def test_본문의_다른_번호는_인용으로_보지_않는다():
    # 앞머리("…에 있어서" 앞)만 읽는다. 본문의 "제1 속도" 같은 말은 인용이 아니다
    got = _deps((1, "방법."), (2, "제1항에 있어서, 제2 속도는 제1 속도보다 빠른 방법."))
    assert got[2] == [1]


def test_앞머리_글자를_남긴다():
    refs = claim_refs(_texts((1, "장치."), (2, "제1항에 있어서, 장치.")))
    assert refs[2].head.startswith("제1항")


def test_글자가_없으면_빈_표와_경고(caplog):
    with caplog.at_level(logging.WARNING):
        assert claim_refs([]) == {}
    assert caplog.text
