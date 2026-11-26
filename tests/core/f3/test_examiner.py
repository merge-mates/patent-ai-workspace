"""심사관 지정 위치 -> 색인 조각 맞추기 테스트. 기대값은 F3 뼈대 설계 6절과 검색 계약 7-4 규칙."""

import pytest

from patent_ai.core.f3_claim_compare.examiner import examiner_locations, match_location
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from tests.core.f3.fakes import chunk, citation, claim_row, oa, paragraph, rejection

DOC = "KR20990000001A"
CHUNKS = [
    paragraph(DOC, 16, "물통은 투명하다", [1.0, 0.0]),
    paragraph(DOC, 23, "센서는 도 4와 같이 놓인다", [1.0, 0.0], figures=[4]),
    paragraph(DOC, 24, "제어부", [1.0, 0.0]),
    chunk(
        DOC, "fig4", "도 4는 화분의 단면도", [1.0, 0.0], kind="figure", label="도 4", figures=[4]
    ),
    chunk(
        DOC,
        "claim9",
        "받침을 포함하는 화분",
        [1.0, 0.0],
        kind="claim",
        label="청구항 9",
        claims=[9],
    ),
    chunk(DOC, "abs", "화분에 관한 것이다", [1.0, 0.0], kind="abstract", label="요약"),
]


def _ids(location: str) -> list[str]:
    return [cid.rsplit(":", 1)[1] for cid in match_location(location, CHUNKS).chunk_ids]


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("[0016]", ["p0016"]),  # 문단 하나
        ("[0022]-[0024]", ["p0023", "p0024"]),  # 범위: 겹치는 문단 모두
        ("도 4", ["fig4", "p0023"]),  # 도면 번호를 담은 조각이면 본문도
        ("도 4c", ["fig4", "p0023"]),  # 가지 글자는 도면 번호로 본다
        ("청구항 9", ["claim9"]),
        ("청구항 8-10", ["claim9"]),  # 청구항 범위 (통지서 구성 대비표 머리)
        ("요약", ["abs"]),
    ],
)
def test_위치를_색인_조각과_맞춘다(location, expected):
    match = match_location(location, CHUNKS)
    assert _ids(location) == expected
    assert match.status.value == StatusValue.CONFIRMED and match.location == location


@pytest.mark.parametrize("location", ["[0099]", "도 7", "청구항 2", "청구항 1-3", "3:5-10"])
def test_못_맞춘_위치는_조각_없이_확인되지_않음(location):
    match = match_location(location, CHUNKS)
    assert match.chunk_ids == []
    assert match.status.value == StatusValue.UNVERIFIED
    assert match.status.reason == UnverifiedReason.EVIDENCE_REJECTED


def test_도면_부호만_짚은_위치는_애매():
    match = match_location("제어부(130)", CHUNKS)
    assert match.chunk_ids == []
    assert match.status.reason == UnverifiedReason.AMBIGUOUS


# ---- 어느 위치를 쓸지: 청구항 줄 -> 같은 취지 줄 -> 인용문헌 칸 ----
def _oa(rows):
    cited = citation("D1", DOC, paragraphs=["[0016]"])
    return oa([rejection(1, "29-2", [1, 2, 3], [cited])], rows)


def test_청구항_줄에_위치가_있으면_그_위치를_쓴다():
    result = _oa([claim_row(1, 1, ["D1"], {"D1": ["[0023]", "도 4"]})])
    assert examiner_locations(result, 1, 1, "D1") == ["[0023]", "도 4"]


def test_같은_취지_줄은_가리키는_줄의_위치를_쓴다():
    rows = [
        claim_row(1, 1, ["D1"], {"D1": ["[0023]"]}),
        claim_row(2, 1, ["D1"], same_as=["claim:1"]),
    ]
    assert examiner_locations(_oa(rows), 1, 2, "D1") == ["[0023]"]


def test_청구항_줄이_없으면_인용문헌_칸의_위치를_쓴다():
    assert examiner_locations(_oa([]), 1, 3, "D1") == ["[0016]"]


def test_위치_없음은_위치로_치지_않는다():
    result = _oa([claim_row(1, 1, ["D1"], {"D1": ["위치 없음 (단순 부가)"]})])
    assert examiner_locations(result, 1, 1, "D1") == []
