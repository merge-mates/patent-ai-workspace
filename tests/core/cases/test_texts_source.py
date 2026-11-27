"""OA 당시 청구항 판·최초 명세서 → F3Inputs (이슈 #205 T2). PDF 없이 가짜 쪽 읽기로."""

from pathlib import Path

import pytest

from patent_ai.core.cases.case_source.parse import ClaimChangeRow
from patent_ai.core.cases.texts_source import build_texts
from patent_ai.core.f1_oa_reader.case_repository import ClaimVersionRow
from patent_ai.core.f1_oa_reader.pages import PdfReadError
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText

OK = Status(value=StatusValue.CONFIRMED, checked="테스트")
BLANK = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
APP = (
    "【발명의 설명】\n【0001】 화분.\n"
    "【청구범위】\n【청구항 1】\n화분.\n【청구항 2】\n제1항의 화분."
)
AMEND = "【보정대상항목】 청구항 1\n【보정방법】 정정\n【보정내용】\n【청구항 1】\n센서 화분."
FILES = {"app.pdf": [APP[:20], APP[20:]], "amend.pdf": [AMEND]}


def _v(version, kind, doc=None, number=None):
    return ClaimVersionRow(f"cv{version}", "c1", version, kind, number, None, doc)


V0 = _v(0, "application", "d_app")
V1 = _v(1, "amendment", "d_amend", "1-1-2099-0000001-11")
PUB = _v(2, "publication", "d_pub", "10-2099-0000001")
PATHS = {"d_app": "app.pdf", "d_amend": "amend.pdf", "d_pub": "pub.pdf"}


def _read(path: Path, document_id: str) -> PageText:
    if path.name not in FILES:
        raise PdfReadError(path.name)
    # 빈 쪽은 extract_pages처럼 글자 층 없음(unverified, body_missing)으로 둔다
    pages = [
        Page(page=i, status=OK if t else BLANK, text=t)
        for i, t in enumerate(FILES[path.name], start=1)
    ]
    return PageText(document_id=document_id, status=OK, pages=pages)


def _build(examined, versions=(V0, V1, PUB), paths=PATHS):
    return build_texts(examined, list(versions), paths, read_pages=_read)


def test_texts_source_출원_때_판이면_출원서_청구항과_명세서():
    got = _build(V0)
    assert got.claims_status.value == StatusValue.CONFIRMED
    assert got.claims_at_oa == {1: "화분.", 2: "제1항의 화분."}
    assert got.claims_document_id == "d_app"
    assert got.spec.document_id == "d_app"  # 최초 명세서 = 출원서


def _hist(claim, text, change="신규"):
    return ClaimChangeRow("112099000000001", str(claim), change, text)


def test_texts_source_줄바꿈만_다르면_청구항이력의_깨끗한_글자를_쓴다():
    # PDF는 줄 폭에서 단어 한가운데를 끊는다 ("화\n분"). 청구항이력은 끊기지 않은 글자다
    files = {"app.pdf": [APP.replace("【청구항 1】\n화분.", "【청구항 1】\n화\n분.")]}
    got = build_texts(
        V0, [V0], {"d_app": "app.pdf"},
        read_pages=lambda p, d: PageText(
            document_id=d, status=OK,
            pages=[Page(page=1, status=OK, text=files[p.name][0])],
        ),
        claim_history=[_hist(1, "화분."), _hist(2, "제1항의<br />화분.")],
    )  # fmt: skip
    # <br />는 청구항 안의 진짜 줄바꿈이다
    assert got.claims_at_oa == {1: "화분.", 2: "제1항의\n화분."}
    assert got.claims_status.value == StatusValue.CONFIRMED


def test_texts_source_글자가_다르면_PDF_글자를_그대로_쓴다():
    # 이력의 다른 판(보정 전 글 등)과 섞이지 않게: 띄어쓰기를 뺀 글자가 같을 때만 바꾼다
    got = build_texts(
        V0, [V0, V1, PUB], PATHS, read_pages=_read,
        claim_history=[_hist(1, "센서 화분."), _hist(2, "제1항의 화분.")],
    )  # fmt: skip
    assert got.claims_at_oa == {1: "화분.", 2: "제1항의 화분."}


def test_texts_source_보정서_판이면_보정을_적용하고_명세서는_출원서():
    got = _build(V1)
    assert got.claims_at_oa == {1: "센서 화분.", 2: "제1항의 화분."}
    assert got.claims_document_id == "d_amend"
    assert got.spec.document_id == "d_app"


def test_texts_source_공보_판은_AI_입력으로_쓰지_않는다():
    assert _build(PUB) is None


def test_texts_source_심사_대상_판을_모르면_None():
    assert _build(None) is None


def test_texts_source_출원서_문서가_없으면_None():
    assert _build(V0, versions=(_v(0, "application"), V1)) is None


def test_texts_source_중간_보정서_문서가_없으면_None():
    v2 = _v(2, "amendment", "d_amend", "1-1-2099-0000002-22")
    assert _build(v2, versions=(V0, _v(1, "amendment"), v2)) is None


def test_texts_source_파일을_못_읽으면_None():
    assert _build(V0, paths={"d_app": "없는.pdf"}) is None


def test_texts_source_뒤_판의_보정서는_적용하지_않는다():
    later = _v(2, "amendment", "d_later", "1-1-2099-0000003-33")
    got = _build(V1, versions=(V0, V1, later), paths={**PATHS, "d_later": "없는.pdf"})
    assert got.claims_at_oa[1] == "센서 화분."


def test_texts_source_번호를_못_뽑으면_글자는_넘기되_unverified():
    FILES["broken.pdf"] = ["【청구범위】\n【청구항 1】\n화분.\n【청구항 3】\n화분."]
    got = _build(V0, paths={"d_app": "broken.pdf"})
    assert got.claims_status.value == StatusValue.UNVERIFIED


def test_texts_source_청구항_사이에_글자_층_없는_쪽이_끼면_unverified():
    # 리뷰 #215 막음: 그림 쪽 글자가 빠진 채 confirmed가 되지 않게 한다
    FILES["a.pdf"] = [
        "【청구범위】\n【청구항 1】\n물통과",
        "",  # 글자 층 없는 쪽
        "센서를 포함하는 화분.\n【청구항 2】\n제1항의 화분.\n【요약서】\n요약.",
    ]
    got = _build(V0, versions=(V0,), paths={"d_app": "a.pdf"})
    assert got.claims_status.value == StatusValue.UNVERIFIED
    assert got.claims_status.reason == UnverifiedReason.BODY_MISSING


def test_texts_source_청구항_범위_밖의_그림_쪽은_상관없다():
    FILES["a.pdf"] = ["【청구범위】\n【청구항 1】\n화분.\n【요약서】\n요약.", ""]
    got = _build(V0, versions=(V0,), paths={"d_app": "a.pdf"})
    assert got.claims_status.value == StatusValue.CONFIRMED


def test_texts_source_보정서_청구항_항목에_글자_층_없는_쪽이_끼면_unverified():
    FILES["m.pdf"] = [
        "【보정대상항목】 청구항 1\n【보정방법】 정정\n【보정내용】\n【청구항 1】\n센서",
        "",
        "화분.\n【보정대상항목】 청구항 2\n【보정방법】 삭제",
    ]
    got = _build(V1, versions=(V0, V1), paths={"d_app": "app.pdf", "d_amend": "m.pdf"})
    assert got.claims_status.value == StatusValue.UNVERIFIED
    assert got.claims_status.reason == UnverifiedReason.BODY_MISSING


@pytest.fixture(autouse=True)
def _clean_files():
    yield
    for name in ("broken.pdf", "a.pdf", "m.pdf"):
        FILES.pop(name, None)
