"""F4 보정 프롬프트의 명세서 발췌 테스트 (이슈 #42 lane_extra C1).

기대값은 지시문에서 가져왔다: 스위치 끔 = 지금 방식(쪽 글자 전체) 그대로, 켬 = BM25 상위 N 문단만
원래 순서로, 근거 위치 대조는 발췌가 아니라 원문 전체, top_n 잘못된 값은 설정 읽기에서 멈춤.
진짜 모델 호출 없음 (FakeTransport).
"""

import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.amendment import (
    STEP,
    _excerpt_query,
    _spec_text,
    build_amendments,
)
from patent_ai.core.f4_response_draft.config import F4Options, load_f4_options
from patent_ai.core.f4_response_draft.directions import build_directions, f3_results
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.opinion import build_opinion
from patent_ai.core.f4_response_draft.spec_excerpt import (
    EXCERPT_NOTE_PROMPT,
    excerpt_spec_text,
    split_paragraphs,
)
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.document import PageText
from tests.core.f4.test_f4_amendment import UNIT_INVENTIVE, _answer, _case, _text


def _status() -> dict:
    return {"value": "confirmed", "reason": None, "checked": "글자 있음", "searched_scope": None}


def _spec(*pages: str) -> PageText:
    return PageText.model_validate(
        {
            "document_id": "spec_1",
            "pages": [
                {"page": n, "text": t, "status": _status(), "tables": []}
                for n, t in enumerate(pages, start=1)
            ],
            "status": _status(),
        }
    )


# 청구항·차이점 글자(센서, 투명 덮개, 간격)와 겹치는 문단 둘 + 안 겹치는 문단들
FILLER_1 = "[0001] 배터리 충전 회로는 전압을 낮추어 셀에 전달한다."
FILLER_2 = "[0002] 통신 모듈의 안테나는 외부 신호를 받는다."
HIT_1 = "[0010] 센서를 덮는 투명 덮개는 센서와 적당한 간격을 두고 놓인다."
HIT_2 = "[0015] 덮개에는 김 서림 방지 막을 둘 수 있다."
FILLER_3 = "[0020] 전원 버튼은 장치 옆면에 있다."
BIG_SPEC = _spec(f"{FILLER_1}\n{FILLER_2}", f"{HIT_1}\n\n{FILLER_3}\n{HIT_2}")


# ---- 문단 나누기 ----
def test_빈_줄이나_식별번호에서_문단을_나눈다():
    spec = _spec("[0001] 가.\n[0002] 나.\n\n다 문단 번호 없음", "【0003】 라.【0004】 마.")
    got = [(page, text) for page, text in split_paragraphs(spec)]
    assert got == [
        (1, "[0001] 가."),
        (1, "[0002] 나."),
        (1, "다 문단 번호 없음"),
        (2, "【0003】 라.【0004】 마."),  # 같은 줄 안 번호는 줄 시작이 아니라 나누지 않는다
    ]


# ---- 스위치 켬: 상위 N 문단만, 원래 순서 ----
def _prompt_spec(inp: F4Input, options: F4Options) -> tuple[str, object]:
    transport = FakeTransport(
        {
            "f4.direction": [
                _text(_answer("direction_inventive")),
                _text(_answer("direction_clarity")),
            ],
            "f4.opinion": [_text(_answer("opinion_inventive")), _text(_answer("opinion_clarity"))],
            STEP: [_text(_answer("amendment_inventive")), _text(_answer("amendment_clarity"))],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    found = build_directions(inp, ctx, options=options)
    opinion = build_opinion(inp, found, ctx, options=options)
    part = build_amendments(inp, found, opinion, ctx, options=options)
    prompt = next(c["prompt"] for c in transport.calls if c["step"] == STEP)
    return prompt, part


def test_스위치를_끄면_프롬프트_명세서_칸은_쪽_글자_전체_그대로다():
    # 저장소 기본 설정(끔)으로 돌린다: 스위치를 무시하는 구현은 여기서 걸린다
    options = load_f4_options()
    assert options.spec_excerpt_enabled is False
    prompt, _ = _prompt_spec(_inp_big(), options)
    expected = f"[쪽 1]\n{FILLER_1}\n{FILLER_2}\n\n[쪽 2]\n{HIT_1}\n\n{FILLER_3}\n{HIT_2}"
    assert expected in prompt
    assert "아래는 최초 명세서 중" not in prompt  # 안내 문구도 없다


def _on(top_n: int) -> F4Options:
    return F4Options(
        final_rejection_limit=False,
        max_units=20,
        max_candidates=3,
        spec_excerpt_enabled=True,
        spec_excerpt_top_n=top_n,
    )


def _inp_big() -> F4Input:
    inp = _case()
    return inp.model_copy(update={"spec": BIG_SPEC})


def test_스위치를_켜면_겹치는_상위_N_문단만_원래_순서로_넣는다():
    inp = _inp_big()
    claims = {1: "기판 위에 놓인 센서와, 상기 센서를 덮는 투명 덮개를 포함하는 가상의 센서 장치."}
    text = excerpt_spec_text(inp.spec, "센서를 덮는 투명 덮개 " + claims[1], top_n=2, unit_id="u")
    assert HIT_1 in text and HIT_2 in text
    for other in (FILLER_1, FILLER_2, FILLER_3):
        assert other not in text
    assert text.index(HIT_1) < text.index(HIT_2)  # 원래 순서
    assert "[쪽 2]" in text and "[쪽 1]" not in text  # 쪽 표시, 문단이 없는 쪽은 안 넣는다


def test_프롬프트에는_발췌만_들어가고_원문_전체는_안_들어간다():
    text, _ = _prompt_spec(_inp_big(), _on(2))
    assert HIT_1 in text and FILLER_1 not in text and FILLER_3 not in text


def test_문단이_N개_이하면_전체를_넣고_로그를_남긴다(caplog):
    inp = _inp_big()
    with caplog.at_level(logging.INFO):
        text = excerpt_spec_text(inp.spec, "센서 덮개", top_n=50, unit_id="u1")
    assert text == _spec_text(inp.spec)
    assert "u1" in caplog.text and "전체" in caplog.text


def test_질의가_비면_전체를_넣는다(caplog):
    inp = _inp_big()
    with caplog.at_level(logging.INFO):
        text = excerpt_spec_text(inp.spec, "   ", top_n=1, unit_id="u1")
    assert text == _spec_text(inp.spec)
    assert "질의" in caplog.text


# ---- 근거 대조는 원문 전체 ----
def test_발췌에_없는_쪽_글자도_원문_전체에_있으면_근거로_통과한다():
    inp = _inp_big()
    # top_n=1이면 발췌에는 HIT_1 문단만 있다. 모델이 준 근거(HIT_2 글자)는 발췌 밖이다
    text, part = _prompt_spec(inp, _on(1))
    assert HIT_2 not in text  # 발췌 밖 문단
    first = part.claims[0]
    assert first.unit_id == UNIT_INVENTIVE
    assert [e.raw_text for e in first.spec_basis] == ["덮개에는 김 서림 방지 막을 둘 수 있다"]
    assert part.statuses[0].value == StatusValue.CONFIRMED


# ---- 설정 ----
def _write(tmp_path: Path, extra: str) -> Path:
    base = (Path(__file__).resolve().parents[3] / "config" / "f4.yaml").read_text("utf-8")
    base = base.split("amendment_spec_excerpt:")[0].split("\ndirection:")[0]
    (tmp_path / "f4.yaml").write_text(base + "\n" + extra, encoding="utf-8")
    return tmp_path


def test_저장소_설정은_발췌가_꺼져_있다():
    options = load_f4_options()
    assert options.spec_excerpt_enabled is False and options.spec_excerpt_top_n >= 1


def test_설정에서_발췌_스위치와_top_n을_읽는다(tmp_path):
    options = load_f4_options(
        _write(tmp_path, "amendment_spec_excerpt: {enabled: true, top_n: 7}\n")
    )
    assert options.spec_excerpt_enabled is True and options.spec_excerpt_top_n == 7


@pytest.mark.parametrize(
    "body",
    [
        "amendment_spec_excerpt: {enabled: true, top_n: 0}",  # 1보다 작음
        "amendment_spec_excerpt: {enabled: true, top_n: -3}",
        "amendment_spec_excerpt: {enabled: true, top_n: '5'}",  # 숫자가 아님
        "amendment_spec_excerpt: {enabled: true, top_n: true}",  # bool은 숫자가 아님
        "amendment_spec_excerpt: {enabled: true}",  # top_n 빠짐
        "amendment_spec_excerpt: {enabled: 'yes', top_n: 5}",  # 참·거짓이 아님
        "amendment_spec_excerpt: {enabled: false, top_n: 0}",  # 끄더라도 값은 맞아야
        "amendment_spec_excerpt: 5",  # 칸 모양이 틀림
        "amendment_spec_excerpt: {enabled: true, top_n: 5, topn: 3}",  # 모르는 키(오타)
    ],
)
def test_발췌_설정이_틀리면_멈춘다(tmp_path, body):
    with pytest.raises(ModelConfigError):
        load_f4_options(_write(tmp_path, body + "\n"))


# ---- 청구범위 덩어리는 후보에서 뺀다 ----
def test_청구범위_덩어리는_발췌_후보에서_빠진다():
    claims = (
        "【청구범위】\n【청구항 1】 센서를 덮는 투명 덮개를 포함하는 센서 장치.\n【청구항 2】 센서"
    )
    spec = _spec(f"{FILLER_1}\n{FILLER_2}\n{HIT_1}\n{FILLER_3}\n{HIT_2}", claims)
    text = excerpt_spec_text(spec, "센서를 덮는 투명 덮개", top_n=2, unit_id="u")
    assert "【청구항" not in text and "【청구범위】" not in text
    assert HIT_1 in text  # 자리를 청구범위가 아니라 명세서 문단이 차지한다


# ---- 안내 문구 파일 ----
@pytest.mark.parametrize("content", [None, "  \n"])  # 파일 없음 / 비어 있음
def test_안내_문구_파일이_없거나_비면_멈춘다(tmp_path, monkeypatch, content):
    monkeypatch.setattr("patent_ai.core.f4_response_draft.spec_excerpt.REPO_ROOT", tmp_path)
    if content is not None:
        note = tmp_path / EXCERPT_NOTE_PROMPT
        note.parent.mkdir(parents=True)
        note.write_text(content, encoding="utf-8")
    with pytest.raises(ModelConfigError):
        excerpt_spec_text(BIG_SPEC, "센서 덮개", top_n=2, unit_id="u")


# ---- 질의 만들기 ----
def _query_for(unit_id: str) -> str:
    inp = _case()
    unit = next(u for u in inp.units if u.unit_id == unit_id)
    return _excerpt_query(inp, unit, f3_results(inp, unit))


def test_질의에_개시됨_줄은_없고_차이_후보와_차이점과_청구항_글자는_있다():
    query = _query_for(UNIT_INVENTIVE)
    assert "센서를 덮는 투명 덮개" in query.split("\n")  # 차이 후보 줄의 구성요소
    assert "덮개가 투명한지는 인용발명 1에 적혀 있지 않음" in query  # 요약 differences
    # 묶음 청구항(1, 2) 글자
    assert "상기 센서와 상기 덮개가 적당한 간격을 두고 떨어진" in query


def test_불명_줄의_구성요소도_질의에_들어간다():
    inp = _case()
    unit = next(u for u in inp.units if u.unit_id == UNIT_INVENTIVE)
    table = inp.tables[0]
    rows = [
        r.model_copy(update={"element": "불명 구성 문구", "judgment": "unclear"})
        for r in table.rows[:1]
    ]
    table = table.model_copy(update={"rows": rows})
    assert "불명 구성 문구" in _excerpt_query(inp, unit, [table])


def test_개시됨_줄의_구성요소는_질의_줄에_따로_없다():
    inp = _case()
    unit = next(u for u in inp.units if u.unit_id == UNIT_INVENTIVE)
    disclosed = [r for r in inp.tables[0].rows if r.judgment == "disclosed"]
    assert disclosed
    lines = _excerpt_query(inp, unit, f3_results(inp, unit)).split("\n")
    assert all(r.element not in lines for r in disclosed)


# ---- 켬인데 전체로 돌아가는 경우는 WARNING ----
def test_안_겹치는_질의면_전체를_넣고_경고에_묶음_번호가_남는다(caplog):
    with caplog.at_level(logging.INFO):
        text = excerpt_spec_text(BIG_SPEC, "zzzz qqqq", top_n=1, unit_id="u9")
    assert text == _spec_text(BIG_SPEC)
    rec = [r for r in caplog.records if "u9" in r.getMessage()]
    assert rec and all(r.levelno == logging.WARNING for r in rec)


@pytest.mark.parametrize(("query", "top_n"), [("센서 덮개", 50), ("   ", 1), ("zzzz qqqq", 1)])
def test_전체로_돌아가는_경우는_모두_WARNING(caplog, query, top_n):
    with caplog.at_level(logging.INFO):
        excerpt_spec_text(BIG_SPEC, query, top_n=top_n, unit_id="u1")
    assert any(r.levelno == logging.WARNING and "u1" in r.getMessage() for r in caplog.records)
