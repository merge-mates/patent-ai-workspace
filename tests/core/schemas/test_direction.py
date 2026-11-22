"""DirectionCandidates(⑤) 테스트. 기대값은 이슈 #164 설계, ADR 0001, docs/data-model.md 4절."""

import logging

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import ExtractedValue, Flag, Status, StatusValue
from patent_ai.core.schemas.direction import (
    ALL_DIRECTIONS_CHECKED,
    AddedSource,
    AmendmentCore,
    AmendmentKind,
    AmendmentLimit,
    CoarseDirection,
    Confidence,
    DirectionCandidate,
    DirectionCandidates,
    DirectionSelection,
    Rebuttal,
    RebuttalType,
    RejectionResponse,
    summarize_direction_status,
)

OK = Status(value="confirmed", checked="원문 대조")
BAD = Status(value="unverified", reason="ambiguous")
REB = {"rejection_kind": "inventive_step", "type": "difference", "summary": "차이점이 있음"}
LIMIT = ExtractedValue[AmendmentLimit](value="initial", raw_text="최초 거절이유통지", status=OK)


def cand(cid="c1", rank=1, confidence="high", coarse="argue_only", **kw):
    data = {
        "status": OK,
        "candidate_id": cid,
        "rank": rank,
        "coarse": coarse,
        "name": "반박만",
        "confidence": confidence,
        "reason": "차이가 분명함",
        "checks": [],
        "per_rejection": [{"rejection": 1, "response": "차이점 주장"}],
        "amendment_core": [],
        "rebuttal": None,
    }
    if coarse in ("argue_only", "amend_and_argue"):
        data["rebuttal"] = REB
    if coarse != "argue_only":
        data["amendment_core"] = [{"claim": 1, "kind": "limit"}]
    if confidence == "low":
        data["flags"] = [Flag.NEEDS_HUMAN_JUDGMENT]
    data.update(kw)
    return DirectionCandidate(**data)


def group(cands=None, selection=..., limit=LIMIT, status=None, **kw):
    cands = [cand()] if cands is None else cands
    if selection is ...:
        selection = {"candidate_id": cands[0].candidate_id, "origin": "ai_default"}
    data = {
        "status": status or summarize_direction_status(cands, limit),
        "unit_id": "oa_1:29-2:c1",
        "candidates": cands,
        "selection": selection,
        "amendment_limit": limit,
    }
    data.update(kw)
    return DirectionCandidates(**data)


def low_group(**kw):
    cands = [cand("c1", None, "low"), cand("c2", None, "low", coarse="amend_only")]
    kw.setdefault("flags", [Flag.NEEDS_HUMAN_JUDGMENT])
    return group(cands, selection=kw.pop("selection", None), **kw)


# ---------- 확신 낮음 ----------


def test_low인데_rank_있으면_거부():
    with pytest.raises(ValidationError, match="rank"):
        cand(confidence="low", rank=1)


def test_low가_아닌데_rank_없으면_거부():
    with pytest.raises(ValidationError, match="rank"):
        cand(confidence="high", rank=None)


def test_low인데_직접판단_flag_없으면_거부():
    with pytest.raises(ValidationError, match="needs_human_judgment"):
        cand(confidence="low", rank=None, flags=[])


def test_모두_low_묶음에_ai_default_거부():
    with pytest.raises(ValidationError, match="rank 1"):
        low_group(selection={"candidate_id": "c1", "origin": "ai_default"})


def test_모두_low_묶음_selection_null_통과():
    g = low_group()
    assert g.selection is None


def test_모두_low_묶음_human_selected_통과():
    g = low_group(selection={"candidate_id": "c2", "origin": "human_selected"})
    assert g.selection.origin == "human_selected"


def test_모두_low_묶음에_묶음_flag_없으면_거부():
    with pytest.raises(ValidationError, match="needs_human_judgment"):
        low_group(flags=[])


def test_ai_default가_rank2를_가리키면_거부():
    cands = [cand("c1", 1), cand("c2", 2, "medium")]
    with pytest.raises(ValidationError, match="rank 1"):
        group(cands, selection={"candidate_id": "c2", "origin": "ai_default"})


def test_사람이_rank2를_골라도_통과():
    cands = [cand("c1", 1), cand("c2", 2, "medium")]
    g = group(cands, selection={"candidate_id": "c2", "origin": "human_selected"})
    assert g.selection.candidate_id == "c2"


def test_rank가_1_3이면_거부():
    with pytest.raises(ValidationError, match="rank"):
        group([cand("c1", 1), cand("c2", 3, "medium")])


def test_rank_중복_거부():
    with pytest.raises(ValidationError, match="rank"):
        group([cand("c1", 1), cand("c2", 1, "medium")])


def test_candidate_id_중복_거부():
    with pytest.raises(ValidationError, match="중복"):
        group([cand("c1", 1), cand("c1", 2, "medium")])


def test_selection이_후보_밖이면_거부():
    with pytest.raises(ValidationError, match="후보 안에 없음"):
        group(selection={"candidate_id": "zz", "origin": "human_selected"})


def test_selection_origin은_두_값만():
    with pytest.raises(ValidationError, match="selection.origin"):
        DirectionSelection(candidate_id="c1", origin="ai_generated")


# ---------- 보정 제한 ----------


def test_보정제한_값_없는데_confirmed_거부():
    lim = ExtractedValue[AmendmentLimit](value=None, status=OK)
    with pytest.raises(ValidationError, match="amendment_limit"):
        group(limit=lim)


def test_보정제한_값_없고_unverified_통과():
    lim = ExtractedValue[AmendmentLimit](value=None, status=BAD)
    g = group(limit=lim)
    assert g.status.value == StatusValue.UNVERIFIED


# ---------- enum ----------


def test_신규성에_hindsight_거부():
    with pytest.raises(ValidationError, match="맞지 않음"):
        Rebuttal(rejection_kind="novelty", type="hindsight", summary="x")


def test_other_종류는_반박_유형_없음():
    with pytest.raises(ValidationError, match="반박 유형이 없음"):
        Rebuttal(rejection_kind="other", type="other", summary="x")


def test_반박_요지는_비지_않음():
    with pytest.raises(ValidationError, match="summary"):
        Rebuttal(rejection_kind="clarity", type="obvious_error", summary=" ")


def test_종류별_허용_유형_통과():
    Rebuttal(rejection_kind="novelty", type="grace_period", summary="공지예외")
    Rebuttal(rejection_kind="clarity", type="clear_from_description", summary="x")


def test_add인데_source_없으면_거부():
    with pytest.raises(ValidationError, match="source"):
        AmendmentCore(claim=1, kind="add")


def test_unchanged에_source_거부():
    with pytest.raises(ValidationError, match="source"):
        AmendmentCore(claim=1, kind="unchanged", source="spec")


def test_add와_source_통과():
    assert AmendmentCore(claim=1, kind="add", source="other_dependent").source == "other_dependent"


def test_응답은_비지_않음():
    with pytest.raises(ValidationError, match="response"):
        RejectionResponse(rejection=1, response=" ")


def test_코드_값_목록():
    assert {e.value for e in Confidence} == {"high", "medium", "low"}
    assert {e.value for e in CoarseDirection} == {"argue_only", "amend_and_argue", "amend_only"}
    assert {e.value for e in AmendmentKind} == {
        "unchanged", "limit", "add", "delete", "correct_error", "clarify",
    }  # fmt: skip
    assert {e.value for e in AddedSource} == {"other_dependent", "spec", "other"}
    assert {e.value for e in AmendmentLimit} == {"initial", "final"}
    assert {e.value for e in RebuttalType} == {
        "difference", "no_motivation", "combination_difficulty", "remarkable_effect",
        "hindsight", "not_substantially_same", "grace_period", "obvious_error",
        "clear_from_description", "other",
    }  # fmt: skip


# ---------- coarse 규칙 ----------


def test_argue_only는_보정_있으면_거부():
    with pytest.raises(ValidationError, match="argue_only"):
        cand(coarse="argue_only", amendment_core=[{"claim": 1, "kind": "limit"}])


def test_argue_only는_rebuttal_필수_unchanged는_허용():
    with pytest.raises(ValidationError, match="rebuttal"):
        cand(coarse="argue_only", rebuttal=None)
    c = cand(coarse="argue_only", amendment_core=[{"claim": 1, "kind": "unchanged"}])
    assert c.amendment_core[0].kind == "unchanged"


def test_amend_and_argue는_보정과_rebuttal_필수():
    with pytest.raises(ValidationError, match="보정"):
        cand(coarse="amend_and_argue", amendment_core=[{"claim": 1, "kind": "unchanged"}])
    with pytest.raises(ValidationError, match="rebuttal"):
        cand(coarse="amend_and_argue", rebuttal=None)


def test_amend_only는_보정_필수_rebuttal_null():
    with pytest.raises(ValidationError, match="보정"):
        cand(coarse="amend_only", amendment_core=[])
    with pytest.raises(ValidationError, match="rebuttal"):
        cand(coarse="amend_only", rebuttal=REB)


# ---------- status 모으기 ----------


def test_status가_안쪽_가장_나쁜_값과_같으면_통과():
    g = group([cand("c1", 1), cand("c2", 2, "medium", status=BAD)])
    assert g.status.value == StatusValue.UNVERIFIED


def test_모두_confirmed면_checked_요약():
    assert group().status.checked == ALL_DIRECTIONS_CHECKED


def test_status가_안쪽과_다르면_거부():
    with pytest.raises(ValidationError, match="status"):
        group([cand("c1", 1, status=BAD)], status=OK)


def test_보정제한_status도_모은다():
    # 도우미 값만이 아니라 DirectionCandidates가 실제로 그 값과 다른 status를 거부하는지 잰다
    lim = ExtractedValue[AmendmentLimit](value=None, status=BAD)
    assert summarize_direction_status([cand()], lim).value == StatusValue.UNVERIFIED
    with pytest.raises(ValidationError, match="status"):
        group(limit=lim, status=OK)


@pytest.mark.parametrize(
    "status",
    [
        Status(value="not_found_in_scope", searched_scope="최초 통지"),
        Status(value="confirmed", checked="대조"),
    ],
)
def test_보정제한_값_없으면_unverified만(status):
    # 값을 모르면 "없음"이 아니라 모름: not_found_in_scope도 거부
    lim = ExtractedValue[AmendmentLimit](value=None, status=status)
    with pytest.raises(ValidationError, match="amendment_limit"):
        group(limit=lim, status=BAD)


# ---------- 모양 ----------


def test_extra_칸_거부():
    with pytest.raises(ValidationError):
        cand(index_id="x")
    with pytest.raises(ValidationError):
        Rebuttal(**REB, extra=1)


def test_왕복():
    cands = [
        cand("c1", 1, coarse="amend_and_argue",
             amendment_core=[{"claim": 1, "kind": "add", "source": "spec"}],
             checks=["권리범위 축소"]),
        cand("c2", 2, "medium"),
        cand("c3", None, "low", coarse="amend_only"),
    ]  # fmt: skip
    g = group(cands, selection={"candidate_id": "c1", "origin": "ai_default"})
    again = DirectionCandidates.model_validate(g.model_dump(mode="json"))
    assert again == g


# ---------- 후보 0개 ----------

NOT_EXTRACTED = Status(value="unverified", reason="not_extracted")


def test_후보_0개_confirmed_거부():
    with pytest.raises(ValidationError, match="후보"):
        DirectionCandidates(
            status=OK,
            unit_id="oa_1:29-2:c1",
            candidates=[],
            selection=None,
            amendment_limit=LIMIT,
            flags=[Flag.NEEDS_HUMAN_JUDGMENT],
        )


def test_후보_0개_unverified_통과():
    g = DirectionCandidates(
        status=NOT_EXTRACTED,
        unit_id="oa_1:29-2:c1",
        candidates=[],
        selection=None,
        amendment_limit=LIMIT,
        flags=[Flag.NEEDS_HUMAN_JUDGMENT],
    )
    assert g.status.reason == "not_extracted"


def test_후보_0개면_도우미가_경고하고_not_extracted(caplog):
    with caplog.at_level(logging.WARNING):
        s = summarize_direction_status([], LIMIT)
    assert s.value == StatusValue.UNVERIFIED and s.reason == "not_extracted"
    assert caplog.records


def test_대응_방향_unit_id_꼴이_틀리면_거부():
    data = group().model_dump(mode="json")
    with pytest.raises(ValidationError, match="unit_id 꼴"):
        DirectionCandidates.model_validate({**data, "unit_id": "nonsense"})


def test_후보와_묶음의_origin은_ai_generated만():
    # 사람 선택은 selection.origin 한 곳에만 (맨 위 origin은 DB 거르기 칸)
    for bad in ("human_selected", "ai_default", "human_edited"):
        with pytest.raises(ValidationError, match="origin"):
            cand(origin=bad)
        with pytest.raises(ValidationError, match="origin"):
            group(origin=bad)
    assert cand().origin == "ai_generated"
    assert group().origin == "ai_generated"


# ---------- 직접 쓰기 선택 (이슈 #70) ----------


def written(text="청구항 1을 삭제하고 반박한다", origin="human_written"):
    return {"written_direction": text, "origin": origin}


def test_직접_쓰기_선택_받음():
    g = low_group(selection=written())
    assert g.selection.written_direction == "청구항 1을 삭제하고 반박한다"
    assert g.selection.candidate_id is None
    assert g.selection.origin == "human_written"


def test_직접_쓰기는_후보_안에_있는지_보지_않음():
    g = group(selection=written())  # 후보는 c1뿐, 글은 후보와 무관
    assert g.selection.candidate_id is None


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_빈_글_거부(text):
    with pytest.raises(ValidationError, match="written_direction"):
        DirectionSelection(written_direction=text, origin="human_written")


def test_candidate_id와_글_둘_다_거부():
    with pytest.raises(ValidationError, match="정확히 하나"):
        DirectionSelection(candidate_id="c1", written_direction="글", origin="human_written")


def test_candidate_id도_글도_없으면_거부():
    with pytest.raises(ValidationError, match="정확히 하나"):
        DirectionSelection(origin="human_selected")


@pytest.mark.parametrize("origin", ["ai_default", "human_selected"])
def test_글_선택에_후보_origin_거부(origin):
    with pytest.raises(ValidationError, match="human_written"):
        DirectionSelection(written_direction="글", origin=origin)


def test_후보_선택에_human_written_거부():
    with pytest.raises(ValidationError, match="ai_default"):
        DirectionSelection(candidate_id="c1", origin="human_written")
