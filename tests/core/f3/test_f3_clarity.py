"""명확성 단계(B3) 테스트: 지어낸 청구항·명세서 + 가짜 응답. 진짜 호출·DB·임베딩 없음.

기대값은 구현 계획(B3)과 "정한 것"(출원서만 메모리 BM25, 짚은 문구 위치는 코드로 확인)에서 가져왔다.
"""

import functools
import json
import logging

import pytest

from patent_ai.core.f3_claim_compare.clarity import (
    STEP,
    build_spec_index,
    review_clarity_unit,
    review_clarity_units,
    split_spec,
)
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText
from tests.core.f3.fakes import OK, bad, claim_row, oa, rejection, split

CLAIMS = {
    1: "화분에 있어서, 물통을 포함하는 화분.",
    2: "제1항에 있어서, 받침을 더 포함하는 화분.",
    3: "제2항에 있어서, 상기 제어 모듈은 대략 원형인 화분.",
}
SPLITS = {1: split(1, ["물통"]), 2: split(2, ["받침"], [1]), 3: split(3, ["제어 모듈"], [2])}
TERM, VAGUE = "상기 제어 모듈", "대략"

SPEC = PageText(
    document_id="d_spec",
    status=OK,
    pages=[
        Page(
            page=1,
            status=OK,
            text=(
                "【0015】 화분은 물통과 받침을 가진다.\n"
                "【0016】 제어 모듈은 밸브를 여닫는 회로 기판을\n말한다."
            ),
        ),
        Page(
            page=2,
            status=OK,
            text="제어 모듈은 받침 안에 놓인다.\n【0017】 뚜껑은 둥글다.",
        ),
    ],
)
SPEC_CHUNKS = split_spec(SPEC)
P16 = next(
    c.chunk.chunk_id for c in SPEC_CHUNKS if c.chunk.location.label == "[0016]" and c.page == 1
)
DEFINITION = "제어 모듈은 밸브를 여닫는 회로 기판을 말한다"


def _oa(terms, claims=(3,)):
    rows = [claim_row(c, 1, clarity_terms=terms) for c in claims]
    return oa([rejection(1, "42-4-2", list(claims))], rows)


def _config(spec=SPEC, claims_status=OK) -> F3Config:
    inputs = F3Inputs(
        claims_at_oa=CLAIMS, claims_status=claims_status, claims_document_id="d_c", spec=spec
    )
    return F3Config(settings=load_f3_settings(), inputs=inputs)


@functools.cache
def _spec_index():
    return build_spec_index(SPEC, load_f3_settings())


def _term(term, issue_type="no_antecedent", note="앞 청구항에 제어 모듈이 나오지 않음", pick=None):
    definition = {"chunk_id": pick[0], "quote": pick[1]} if pick else None
    return {"term": term, "issue_type": issue_type, "note": note, "definition": definition}


def _answer(terms: list[dict], claim: int = 3) -> TransportResponse:
    return TransportResponse(
        json.dumps({"claim": claim, "terms": terms}, ensure_ascii=False), 100, 50
    )


def _run(result, responses, config=None):
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    units, _ = build_units(result, SPLITS)
    config = config or _config()
    # 형태소 분석기를 테스트마다 다시 띄우지 않게 같은 명세서의 색인은 한 번만 만든다
    index = _spec_index() if config.inputs.spec is SPEC else None
    out = review_clarity_unit(units[0], result, config, ctx=ctx, spec_index=index)
    return out, transport.calls


# ---- 명세서 쪼개기 ----
def test_명세서는_쪽_안에서_식별번호마다_쪼개고_쪽을_넘은_글은_앞_식별번호로_잇는다():
    told = [(c.chunk.location.label, c.page) for c in SPEC_CHUNKS]
    assert told == [("[0015]", 1), ("[0016]", 1), ("[0016]", 2), ("[0017]", 2)]
    assert all(c.chunk.doc_id == "d_spec" for c in SPEC_CHUNKS)
    assert "받침 안에 놓인다" in SPEC_CHUNKS[2].chunk.text


def test_식별번호가_없는_쪽은_쪽_하나가_조각이다():
    page = Page(page=1, status=OK, text="화분은 물통을 가진다.")
    (only,) = split_spec(PageText(document_id="d", status=OK, pages=[page]))
    assert (only.chunk.location.kind, only.chunk.location.label, only.page) == ("page", "1쪽", 1)


# ---- 짚은 문구 위치 ----
def test_짚은_문구를_청구항_원문에서_찾아_위치를_적는다():
    answer = _answer(
        [_term(TERM, pick=(P16, DEFINITION)), _term(VAGUE, "optional_expression", "정도가 불분명")]
    )
    out, calls = _run(_oa([TERM, VAGUE]), answer)
    assert len(calls) == 1 and out.held_tasks == []
    first, second = out.reviews
    assert (first.unit_id, first.claim, first.term) == ("oa_1:42-4-2:c3", 3, TERM)
    start = CLAIMS[3].index(TERM)
    assert first.claim_location == f"청구항 3 [글자 {start}-{start + len(TERM)}]"
    assert second.term == VAGUE and second.claim_location.startswith("청구항 3 [글자 ")
    assert first.note and "앞 청구항에 제어 모듈이 나오지 않음" in first.note


def test_청구항_원문에_없는_문구는_확인되지_않음으로_남긴다(caplog):
    answer = _answer([_term(TERM, pick=(P16, DEFINITION))])
    with caplog.at_level(logging.WARNING):
        out, calls = _run(_oa([TERM, "상기 통신부"]), answer)
    first, lost = out.reviews  # 조용히 빼지 않는다
    assert first.status.value == StatusValue.CONFIRMED
    assert lost.term == "상기 통신부" and lost.spec_definition is None
    assert lost.status.value == StatusValue.UNVERIFIED
    assert lost.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert "상기 통신부" not in calls[0]["prompt"]  # 못 찾은 문구는 모델에 묻지 않는다
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_인용하는_앞_청구항_글자가_프롬프트에_들어간다():
    _, calls = _run(_oa([TERM]), _answer([_term(TERM)]))
    prompt = calls[0]["prompt"]
    assert CLAIMS[1] in prompt and CLAIMS[2] in prompt and CLAIMS[3] in prompt


# ---- 정의 근거 대조 ----
def test_명세서에_그대로_있는_정의_근거는_위치와_함께_싣는다():
    out, _ = _run(_oa([TERM]), _answer([_term(TERM, pick=(P16, DEFINITION))]))
    (review,) = out.reviews
    found = review.spec_definition
    assert (found.document_id, found.page, found.location) == ("d_spec", 1, "[0016]")
    assert found.raw_text == "제어 모듈은 밸브를 여닫는 회로 기판을\n말한다"  # 명세서 글자 그대로
    assert review.status.value == StatusValue.CONFIRMED


@pytest.mark.parametrize(
    "pick",
    [
        (P16, "제어 모듈은 통신을 맡는 회로를 말한다"),  # 명세서에 없는 글자
        (P16, "제어"),  # 너무 짧은 글자 (아무 데나 맞는다)
        ("없는:조각", DEFINITION),  # 후보에 없는 조각
    ],
)
def test_대조에_떨어진_정의_근거는_한_번_다시_부르고_그래도_틀리면_버린다(pick):
    wrong = _answer([_term(TERM, pick=pick)])
    out, calls = _run(_oa([TERM]), [wrong, wrong])
    assert len(calls) == 2 and "검사 오류" in calls[1]["prompt"]
    (review,) = out.reviews
    assert review.spec_definition is None
    assert review.status.reason == UnverifiedReason.EVIDENCE_REJECTED


def test_정의를_못_고르면_조회_범위_내_없음과_찾아본_범위를_남긴다():
    out, _ = _run(_oa([TERM]), _answer([_term(TERM)]))
    (review,) = out.reviews
    assert review.spec_definition is None
    assert review.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert review.status.searched_scope == "출원서 조각 4개 중 bm25 상위 5"


def test_명세서가_없으면_본문_미확보이고_문제_유형은_그대로_본다():
    out, calls = _run(_oa([TERM]), _answer([_term(TERM)]), _config(spec=None))
    (review,) = out.reviews
    assert len(calls) == 1
    assert review.status.reason == UnverifiedReason.BODY_MISSING
    assert review.spec_definition is None and review.note


# ---- 남기는 것 ----
def test_OA가_문구를_짚지_않은_줄은_검토를_못_만들고_보류로_남긴다(caplog):
    with caplog.at_level(logging.WARNING):
        out, calls = _run(_oa([]), [])
    assert out.reviews == [] and calls == []
    assert [h.task for h in out.held_tasks] == ["f3_clarity:oa_1:42-4-2:c3"]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_모델이_빼먹은_문구는_버리지_않고_확인되지_않음():
    partial = _answer([_term(TERM, pick=(P16, DEFINITION))])
    out, calls = _run(_oa([TERM, VAGUE]), [partial, partial])
    assert len(calls) == 2
    first, second = out.reviews
    assert first.status.value == StatusValue.CONFIRMED
    assert second.term == VAGUE and second.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_청구항_판이_확인되지_않으면_input_unverified():
    config = _config(claims_status=bad(UnverifiedReason.EDITION_UNKNOWN))
    out, _ = _run(_oa([TERM]), _answer([_term(TERM, pick=(P16, DEFINITION))]), config)
    assert out.reviews[0].status.reason == UnverifiedReason.INPUT_UNVERIFIED


def test_두_번_다_형식이_틀리면_예외로_끝난다():
    broken = TransportResponse("검토 결과입니다", 100, 50)
    with pytest.raises(ModelOutputInvalid):
        _run(_oa([TERM]), [broken, broken])


def test_명확성_단위만_골라_순서대로_검토한다():
    result = oa(
        [rejection(1, "29-2", [1]), rejection(2, "42-4-2", [3])],
        [claim_row(3, 2, clarity_terms=[TERM])],
    )
    units, _ = build_units(result, SPLITS)
    transport = FakeTransport({STEP: [_answer([_term(TERM)])]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    out = review_clarity_units(units, result, _config(), ctx=ctx)
    assert [r.unit_id for r in out.reviews] == ["oa_1:42-4-2:c3"]


def test_clarity_단계_설정():
    cfg = load_step_config("f3.clarity")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-haiku-5-5", "medium", 64000)
    assert cfg.prompt == "prompts/f3/clarity.md" and cfg.max_model_calls is not None
    settings = load_f3_settings()
    assert settings.clarity_search.k >= 1 and settings.min_quote_chars >= 1


# ---- B3 리뷰 고침 ----
def test_청구범위와_요약서_글은_명세서_조각에_넣지_않는다():
    # 청구항 글이 앞 문단 조각에 붙으면 청구항이 자기 정의 근거가 되고 위치도 틀리게 붙는다
    text = (
        "【0050】 끝 문단.\n【청구범위】\n【청구항 1】\n상기 제어 모듈을 포함하는 화분.\n"
        "【요약서】\n【요약】\n제어 모듈을 가진 화분에 관한 것이다.\n【도면】\n【도 1】"
    )
    spec = PageText(document_id="d", status=OK, pages=[Page(page=1, status=OK, text=text)])
    chunks = split_spec(spec, load_f3_settings().clarity_search.skip_headings)
    assert [(c.chunk.location.label, c.chunk.text) for c in chunks] == [
        ("[0050]", "【0050】 끝 문단.")
    ]


def test_뺀_구간_뒤에_식별번호가_다시_나오면_다시_조각으로_만든다():
    text = "【청구범위】\n【청구항 1】\n화분.\n【발명의 설명】\n【0001】 화분에 관한 것이다."
    spec = PageText(document_id="d", status=OK, pages=[Page(page=1, status=OK, text=text)])
    chunks = split_spec(spec, load_f3_settings().clarity_search.skip_headings)
    assert [c.chunk.location.label for c in chunks] == ["[0001]"]


def test_청구범위_구간은_다음_쪽으로_이어져도_뺀다():
    pages = [
        Page(page=1, status=OK, text="【0050】 끝 문단.\n【청구범위】\n【청구항 1】\n화분."),
        Page(page=2, status=OK, text="【청구항 2】\n상기 제어 모듈을 더 포함하는 화분."),
    ]
    spec = PageText(document_id="d", status=OK, pages=pages)
    chunks = split_spec(spec, load_f3_settings().clarity_search.skip_headings)
    assert [(c.chunk.location.label, c.page) for c in chunks] == [("[0050]", 1)]


def test_청구항_글은_정의_근거_후보로_모델에_가지_않는다():
    claim_like = "상기 제어 모듈은 대략 원형인 화분."
    page = Page(
        page=1,
        status=OK,
        text=(
            "【0016】 제어 모듈은 밸브를 여닫는 회로 기판을 말한다.\n"
            f"【청구범위】\n【청구항 3】\n{claim_like}"
        ),
    )
    spec = PageText(document_id="d_spec2", status=OK, pages=[page])
    _, calls = _run(_oa([TERM]), _answer([_term(TERM)]), _config(spec=spec))
    shown = calls[0]["prompt"].split("짚은 문구와 명세서 후보 조각")[1]
    assert "회로 기판" in shown and claim_like not in shown


def test_같은_문구가_청구항에_여러_번_나오면_몇_곳인지_적는다():
    claims = {
        **CLAIMS,
        3: "제2항에 있어서, 상기 제어 모듈은 원형이고, 상기 제어 모듈은 방수인 화분.",
    }
    config = _config()
    config = config.model_copy(
        update={"inputs": config.inputs.model_copy(update={"claims_at_oa": claims})}
    )
    out, _ = _run(_oa([TERM]), _answer([_term(TERM)]), config)
    start = claims[3].index(TERM)
    expected = f"청구항 3 [글자 {start}-{start + len(TERM)}] (2곳 중 첫 자리)"
    assert out.reviews[0].claim_location == expected
