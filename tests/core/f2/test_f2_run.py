"""F2 task-3: run_f2 (판단 단위 -> 법률 근거 묶음). 모델·DB 없음, 메모리 저장소."""

import logging
from datetime import date

from patent_ai.core.f2_legal_research import run as f2_run
from patent_ai.core.f2_legal_research.run import F2Input, F2Settings, load_f2_settings, run_f2
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.schemas.common import ExtractedValue, Flag, StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import AsOfSource, LegalSourceKind
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f2 import fakes
from tests.core.f2.fakes import IV, NEW_DOC, TEXT_292_NEW, TEXT_424_NEW
from tests.core.f3.fakes import OK, oa, rejection, split

CHECKED_ON = date(2099, 2, 1)
AS_OF = date(2099, 1, 26)  # tests/core/f3/fakes.oa 발송일 글자 "2099.01.26."


def _oa(**fields):
    built = oa([rejection(1, "29-2", [1]), rejection(2, "42-4-2", [2], reasoning="불명확")])
    return built.model_copy(update=fields) if fields else built


def _input(o=None) -> F2Input:
    o = o or _oa()
    units, _ = build_units(o, {1: split(1, ["가"]), 2: split(2, ["나"], [1])})
    return F2Input(oa=o, units=units, checked_on=CHECKED_ON, settings=F2Settings(index_version=IV))


def test_판단_단위마다_발송일_시행판_조문이_근거로_붙는다():
    out = run_f2(_input(), repo=fakes.repo())
    assert [b.unit_id for b in out.bundles] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    assert [b.bundle_id for b in out.bundles] == ["lb:oa_1:29-2:c1", "lb:oa_1:42-4-2:c2"]
    inventive, clarity = out.bundles
    for bundle, label, text in (
        (inventive, "특허법 제29조제2항", TEXT_292_NEW),
        (clarity, "특허법 제42조제4항제2호", TEXT_424_NEW),
    ):
        q = bundle.question
        assert (q.as_of, q.as_of_source, q.article_refs) == (
            AS_OF,
            AsOfSource.OA_DISPATCH_DATE,
            [label],
        )
        [claim] = bundle.claims
        [source] = claim.sources
        assert source.source_kind == LegalSourceKind.STATUTE and source.identifier == label
        ev = source.evidence
        assert (ev.document_id, ev.raw_text, ev.index_version) == (NEW_DOC, text, IV)
        assert ev.chunk_id.startswith(f"{IV}:{NEW_DOC}:") and ev.edition.startswith(NEW_DOC)
        assert ev.checked_on == CHECKED_ON
        # 근거 검토(모델)는 아직 없다: 확인됨이어도 사람이 봐야 한다고 표시
        assert claim.review is None and Flag.NEEDS_HUMAN_REVIEW in claim.flags
        assert bundle.status.value == StatusValue.CONFIRMED
    assert out.status.value == StatusValue.CONFIRMED and out.oa_id == "oa_1"


def test_심사기준_판례는_색인_전이라_body_missing으로_찾아본_기록만_남는다():
    bundle = run_f2(_input(), repo=fakes.repo()).bundles[0]
    kinds = [(e.source_kind, e.queries) for e in bundle.search_log]
    assert kinds == [
        (LegalSourceKind.STATUTE, 1),
        (LegalSourceKind.GUIDELINE, 0),
        (LegalSourceKind.PRECEDENT, 0),
    ]


def test_발송일을_못_읽으면_조문을_찾지_않고_확인되지_않음(caplog):
    # 원문 글자에 날짜 꼴이 없음 (F1은 확인됨으로 두었어도 날짜로 읽을 수 없다)
    o = _oa(notice_date=ExtractedValue(value=None, raw_text="날짜 없음", page=1, status=OK))
    with caplog.at_level(logging.WARNING):
        out = run_f2(_input(o), repo=fakes.repo())
    for b in out.bundles:
        assert b.claims == [] and b.search_log == []
        assert (b.status.value, b.status.reason) == (
            StatusValue.UNVERIFIED,
            UnverifiedReason.INPUT_UNVERIFIED,
        )
        assert b.question.as_of is None and b.question.as_of_source == AsOfSource.NONE
    assert "발송일" in caplog.text


def test_그날_판이_색인에_없으면_조회_범위_내_없음_묶음():
    only_old = InMemoryChunkRepository({"law": fakes.chunks()[:1]})  # 29조 2항 구판만
    out = run_f2(_input(), repo=only_old)
    for b in out.bundles:
        assert b.claims == [] and b.status.value == StatusValue.NOT_FOUND_IN_SCOPE
        assert b.status.searched_scope
    assert out.status.value == StatusValue.NOT_FOUND_IN_SCOPE


def test_출처_확인에서_빠진_근거는_넣지_않는다(monkeypatch):
    monkeypatch.setattr(f2_run, "check_source", lambda *a, **k: False)
    out = run_f2(_input(), repo=fakes.repo())
    for b in out.bundles:
        assert b.claims == []
        assert b.status.reason == UnverifiedReason.EVIDENCE_REJECTED


def test_판단_단위가_없으면_경고와_확인되지_않음(caplog):
    inp = _input().model_copy(update={"units": []})
    with caplog.at_level(logging.WARNING):
        out = run_f2(inp, repo=fakes.repo())
    assert out.bundles == [] and out.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert "판단 단위가 없음" in caplog.text


def test_repo가_없으면_make_law_repo로_만든다(monkeypatch):
    monkeypatch.setattr(f2_run, "make_law_repo", fakes.repo)
    assert run_f2(_input()).status.value == StatusValue.CONFIRMED


def test_저장소_설정을_읽는다():
    assert load_f2_settings().index_version == "law-idx-v2"
