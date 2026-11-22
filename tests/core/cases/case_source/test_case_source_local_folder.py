"""받아 둔 폴더 구현 (이슈 #54 task-2). tmp 폴더에 지어낸 사건을 둔다."""

from pathlib import Path

import pytest

from patent_ai.core.cases.case_source.base import Missing
from patent_ai.core.cases.case_source.cut import lookup_case
from patent_ai.core.cases.case_source.local_folder import LocalFolderSource, load_case_source
from patent_ai.core.schemas.common import UnverifiedReason

APP = "1020990000001"
FILING = "112099000000101"
OA = "952099000000001"
ADMIN = (
    "출원번호¶접수발송번호¶접수발송일자¶접수발송서류명\n"
    f"{APP}¶{FILING}¶20990101¶[특허출원]특허출원서\n"
    f"{APP}¶{OA}¶20990401¶의견제출통지서\n"
)
CLAIMS = (
    "출원번호¶접수발송일련번호¶접수발송번호¶청구항번호¶변경구분코드¶변경구분명¶청구항\n"
    f"{APP}¶1¶{FILING}¶1¶I¶신규¶가<br />\n"
)


def make_case(root: Path, *, filing: bool = True) -> Path:
    folder = root / APP / OA
    folder.mkdir(parents=True)
    (folder / f"{APP}_행정이력.txt").write_text(ADMIN, encoding="utf-8")
    (folder / f"{APP}_청구항이력.txt").write_text(CLAIMS, encoding="utf-8")
    (folder / f"{APP}_OA_{OA}.pdf").write_bytes(b"%PDF-")
    if filing:
        (folder / f"{APP}_출원서_{FILING}.pdf").write_bytes(b"%PDF-")
    return folder


def test_폴더의_세_자료를_읽어_자른다(tmp_path):
    folder = make_case(tmp_path)
    got = lookup_case(LocalFolderSource(tmp_path), APP, OA)
    assert got.missing == [] and got.source == "local_folder"
    assert got.cut.admin[-1].number == OA
    assert got.application_document == folder / f"{APP}_출원서_{FILING}.pdf"


def test_폴더가_없으면_셋_다_없음과_이유(tmp_path):
    got = lookup_case(LocalFolderSource(tmp_path), APP, OA)
    assert [m.what for m in got.missing] == [
        "claim_history",
        "admin_history",
        "application_document",
    ]
    assert {m.reason for m in got.missing} == {UnverifiedReason.LOOKUP_FAILED}
    assert got.cut is None and got.application_document is None


def test_출원서만_없으면_그것만_없음(tmp_path):
    make_case(tmp_path, filing=False)
    got = lookup_case(LocalFolderSource(tmp_path), APP, OA)
    assert got.missing == [
        Missing(
            "application_document", UnverifiedReason.LOOKUP_FAILED, "받아 둔 폴더에 출원서 없음"
        )
    ]
    assert got.cut is not None


def test_설정으로_구현을_고르고_상대_경로는_저장소_뿌리_기준(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"impl: local_folder\nroot: {tmp_path}\n", encoding="utf-8")
    assert load_case_source(cfg).name == "local_folder"


@pytest.mark.parametrize("body", ["impl: kipris_typo\n", "impl: local_folder\n", ""])
def test_모르는_impl이나_root_없음은_설정_오류(tmp_path, body):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        load_case_source(cfg)


def test_저장소_설정_파일이_읽힌다():
    assert load_case_source().name == "local_folder"
