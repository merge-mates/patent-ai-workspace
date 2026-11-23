"""F2 task-3: run_f2 (판단 단위 -> 법률 근거 묶음). 모델·DB 없음, 메모리 저장소."""

import logging
from datetime import date

import pytest
import yaml

from patent_ai.core.f2_legal_research import run as f2_run
from patent_ai.core.f2_legal_research import tools as f2_tools
from patent_ai.core.f2_legal_research.run import F2Input, F2Settings, load_f2_settings, run_f2
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.schemas.common import ExtractedValue, Flag, StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import AsOfSource, LegalSourceKind
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f2 import fakes
from tests.core.f2.fakes import IV, NEW_DOC, SEARCH, TEXT_292_NEW, TEXT_424_NEW
from tests.core.f3.fakes import OK, bad, oa, rejection, split

CHECKED_ON = date(2099, 2, 1)
AS_OF = date(2099, 1, 26)  # tests/core/f3/fakes.oa 발송일 글자 "2099.01.26."


def _oa(**fields):
    built = oa([rejection(1, "29-2", [1]), rejection(2, "42-4-2", [2], reasoning="불명확")])
    return built.model_copy(update=fields) if fields else built


def _input(o=None) -> F2Input:
    o = o or _oa()
    units, _ = build_units(o, {1: split(1, ["가"]), 2: split(2, ["나"], [1])})
    return F2Input(
        oa=o, units=units, checked_on=CHECKED_ON, settings=F2Settings(index_version=IV, **SEARCH)
    )


def test_판단_단위마다_발송일_시행판_조문이_근거로_붙는다():
    out = run_f2(_input(), repo=fakes.repo())
    assert [b.unit_id for b in out.bundles] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    assert [b.bundle_id for b in out.bundles] == ["lb:oa_1:29-2:c1", "lb:oa_1:42-4-2:c2"]
    inventive, clarity = out.bundles
    for bundle, label, text, loc in (
        (inventive, "특허법 제29조제2항", TEXT_292_NEW, "제29조제2항"),
        (clarity, "특허법 제42조제4항제2호", TEXT_424_NEW, "제42조제4항"),
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
        assert ev.location == loc  # 원문 위치 = 조각 loc_label 그대로
        assert ev.chunk_id.startswith(f"{IV}:{NEW_DOC}:") and ev.edition.startswith(NEW_DOC)
        assert ev.checked_on == CHECKED_ON
        # 근거 검토(모델)는 아직 없다: 확인됨이어도 사람이 봐야 한다고 표시
        assert claim.review is None and Flag.NEEDS_HUMAN_REVIEW in claim.flags
        assert bundle.status.value == StatusValue.CONFIRMED
    assert out.status.value == StatusValue.CONFIRMED and out.oa_id == "oa_1"


def test_심사기준_판례_심결은_그_유형_조각이_0개라_body_missing이_기록에_남는다():
    bundle = run_f2(_input(), repo=fakes.repo()).bundles[0]
    # 묶음은 조문으로 확인됨이어도, 안 본 유형과 그 이유가 search_log status에 남는다
    assert bundle.status.value == StatusValue.CONFIRMED
    rows = [(e.source_kind, e.queries, e.status.value, e.status.reason) for e in bundle.search_log]
    assert rows == [
        (LegalSourceKind.STATUTE, 1, StatusValue.CONFIRMED, None),
        (LegalSourceKind.GUIDELINE, 0, StatusValue.UNVERIFIED, UnverifiedReason.BODY_MISSING),
        (LegalSourceKind.PRECEDENT, 0, StatusValue.UNVERIFIED, UnverifiedReason.BODY_MISSING),
        (LegalSourceKind.TRIAL, 0, StatusValue.UNVERIFIED, UnverifiedReason.BODY_MISSING),
    ]


def test_심사기준_조각이_있으면_BM25로_찾아_근거_후보로만_남긴다():
    guide = fakes.law_chunk(
        "심사기준_101_20200101", 1, "1쪽 (제3부 제3장)", "결합 논리 진보성 판단 심사기준 글",
        fakes.NEW, kind="guideline",
    ).model_copy(update={"source_kind": "guideline"})  # fmt: skip
    bundle = run_f2(_input(), repo=fakes.repo([guide])).bundles[0]
    log = {e.source_kind: e for e in bundle.search_log}[LegalSourceKind.GUIDELINE]
    assert log.hits == 1 and log.status.value == StatusValue.CONFIRMED
    # 주장(근거 검토는 #29)에는 안 올리고 더 볼 것으로만 둔다
    assert [c.chunk_id for c in bundle.further_review] == [guide.chunk_id]
    assert len(bundle.claims) == 1 and len(bundle.claims[0].sources) == 1


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


def test_그날_판이_색인에_없으면_확인되지_않음_어느_판에도_없으면_조회_범위_내_없음():
    only_old = InMemoryChunkRepository({"law": fakes.chunks()[:1]})  # 29조 2항 구판만
    inventive, clarity = run_f2(_input(), repo=only_old).bundles
    # 29조 2항: 구판만 있고 발송일(2099) 판이 없음 -> 판을 모름
    assert inventive.claims == [] and inventive.status.reason == UnverifiedReason.EDITION_UNKNOWN
    # 42조 4항: 어느 판에도 없음 -> 찾아본 범위 안에 없음
    assert clarity.claims == [] and clarity.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert clarity.status.searched_scope


def test_출처_확인에서_빠진_근거는_넣지_않는다(monkeypatch):
    monkeypatch.setattr(f2_tools, "check_source", lambda *a, **k: False)
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
    assert load_f2_settings().index_version == "law-idx-v3"
    assert load_f2_settings().bm25["unique_query_terms"] is True


@pytest.mark.parametrize("missing", ["source_search_k", "tokenizer", "bm25"])
def test_검색_칸이_빠지면_기본값으로_때우지_않고_멈춘다(tmp_path, missing):
    data = {"index_version": IV, **SEARCH}
    del data[missing]
    (tmp_path / "f2.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ModelConfigError):
        load_f2_settings(tmp_path)


def test_bm25_칸이_비어도_멈춘다(tmp_path):
    data = {"index_version": IV, **SEARCH, "bm25": {}}
    (tmp_path / "f2.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ModelConfigError):
        load_f2_settings(tmp_path)


def test_법령_색인이_저장소에_없으면_없음이_아니라_확인되지_않음(caplog):
    # 색인을 안 올린 DB: 못 본 것을 "조회 범위 내 없음"으로 내지 않는다
    with caplog.at_level(logging.WARNING):
        out = run_f2(_input(), repo=InMemoryChunkRepository({"law": []}))
    assert len(out.bundles) == 2
    for b in out.bundles:
        assert b.claims == [] and b.search_log == []
        assert (b.status.value, b.status.reason) == (
            StatusValue.UNVERIFIED,
            UnverifiedReason.BODY_MISSING,
        )
        assert b.question.article_refs  # 질문은 남긴다
    assert out.status.reason == UnverifiedReason.BODY_MISSING
    assert IV in caplog.text


def test_같은_날_시행판이_둘이면_고르지_않고_겹친_조각을_더_볼_것으로_남긴다():
    twin = fakes.law_chunk("특허법_1009_20200101", 290002, "제29조제2항", "겹친 판", fakes.NEW)
    out = run_f2(_input(), repo=fakes.repo([twin]))
    inventive = out.bundles[0]
    assert inventive.claims == []
    assert inventive.status.reason == UnverifiedReason.AMBIGUOUS
    assert sorted(f.chunk_id for f in inventive.further_review) == [
        f"{IV}:{NEW_DOC}:290002",
        f"{IV}:특허법_1009_20200101:290002",
    ]
    assert all("시행판이 둘 이상" in f.note for f in inventive.further_review)
    assert inventive.search_log[0].hits == 2
    # 다른 단위(42조)는 그대로 확인됨
    assert out.bundles[1].status.value == StatusValue.CONFIRMED


def test_발송일이_확인되지_않음이면_글자가_있어도_조문을_찾지_않는다():
    nd = ExtractedValue(value=None, raw_text="2099.01.26.", page=1, status=bad())
    o = _oa(notice_date=nd)
    units, _ = build_units(o, {1: split(1, ["가"]), 2: split(2, ["나"], [1])})
    # OA 전체 status는 칸을 모은 값이라, 검사를 거치지 않는 model_construct로 칸만 바꾼다
    inp = F2Input.model_construct(
        oa=o, units=units, checked_on=CHECKED_ON, settings=F2Settings(index_version=IV, **SEARCH)
    )
    for b in run_f2(inp, repo=fakes.repo()).bundles:
        assert b.claims == [] and b.status.reason == UnverifiedReason.INPUT_UNVERIFIED


def test_단위가_가리키는_거절이유가_OA에_없으면_확인되지_않음(caplog):
    inp = _input()
    only_first = inp.oa.model_copy(update={"rejections": inp.oa.rejections[:1]})
    inp = inp.model_copy(update={"oa": only_first})
    with caplog.at_level(logging.WARNING):
        out = run_f2(inp, repo=fakes.repo())
    assert out.bundles[0].status.value == StatusValue.CONFIRMED
    assert out.bundles[1].status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert "OA에 없음" in caplog.text
