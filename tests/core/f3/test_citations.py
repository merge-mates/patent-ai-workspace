"""인용문헌 -> 색인 doc_id·대비 여부 테스트. 기대값은 F3 뼈대 설계 5절."""

from patent_ai.core.f3_claim_compare.citations import resolve_citations
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import IV, citation, oa, paragraph, rejection

REPO = InMemoryChunkRepository({"cite": [paragraph("KR20990000001A", 23, "물통", [1.0, 0.0])]})


def _resolve(*citations):
    result = oa([rejection(1, "29-2", [1], citations)])
    return resolve_citations(result.rejections[0], "oa_1", REPO, IV)


def test_색인에_조각이_있는_한국_문헌은_대비한다():
    (found,) = _resolve(citation("D1", "KR20990000001A"))
    assert found.doc_id == "KR20990000001A" and found.chunk_count == 1
    assert found.compared.compared is True and found.compared.label == "D1"
    assert found.compared.number == "KR20990000001A"
    assert found.held_task is None


def test_지원_안_하는_나라는_대비하지_않고_직접_확인():
    (found,) = _resolve(citation("D1", "JP2099000001A", country="JP"))
    c = found.compared
    assert c.compared is False
    assert c.skipped_reason == "지원 안 하는 나라 (JP) · 직접 확인"
    assert c.skipped_status.value == StatusValue.UNVERIFIED
    assert c.skipped_status.reason == UnverifiedReason.LOOKUP_FAILED
    assert found.held_task is None  # 올려 달라고 하지 않는다


def test_조각이_0개면_본문_미확보이고_보류로_남긴다():
    (found,) = _resolve(citation("D2", "KR20990000002A"))
    c = found.compared
    assert c.compared is False and found.chunk_count == 0
    assert c.skipped_reason == "본문 미확보 · 올려 주면 대비"
    assert c.skipped_status.reason == UnverifiedReason.BODY_MISSING
    assert found.held_task.task == "f3_compare:oa_1:D2"


def test_미국_문헌도_조각이_없으면_본문_미확보():
    (found,) = _resolve(citation("D1", "US20990000001A1", country="US"))
    assert found.compared.skipped_status.reason == UnverifiedReason.BODY_MISSING


def test_번호를_못_읽은_문헌은_애매로_대비하지_않는다():
    (found,) = _resolve(citation("D1", None))
    c = found.compared
    assert c.compared is False and found.doc_id is None
    assert c.skipped_status.reason == UnverifiedReason.AMBIGUOUS
    assert c.number == "어느 학회 논문"  # 원문 표기를 그대로 보인다


def test_나라를_못_정한_문헌도_애매():
    (found,) = _resolve(citation("D1", "KR20990000001A", country=None))
    assert found.compared.compared is False
    assert found.compared.skipped_status.reason == UnverifiedReason.AMBIGUOUS


def test_여러_문헌은_OA_순서대로():
    found = _resolve(citation("D1", "KR20990000001A"), citation("D2", "JP1A", country="JP"))
    assert [(f.label, f.compared.compared) for f in found] == [("D1", True), ("D2", False)]
