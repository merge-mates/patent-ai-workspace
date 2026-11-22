"""F2 근거 검토 정답 형식 검사 (eval/f2/gold.py). 사례 값은 모두 만든 값이다."""

import copy
import json

import pytest

from eval.common.errors import EvalError
from eval.f2.gold import (
    InjectedCase,
    NoGold,
    RealCase,
    check_set_size,
    count_cases,
    load_f2_cases,
    main,
)

ERRORS = [
    "nonexistent_source",
    "claim_text_mismatch",
    "other_edition_asserted",
    "summary_as_full",
    "old_deadline_as_current",
]


def question(as_of="2020-01-01"):
    return {
        "text": "가짜 질문: 가짜 요건은 무엇인가",
        "source": "oa_rejection",
        "as_of": as_of,
        "as_of_source": "oa_dispatch_date" if as_of else "none",
        "source_kinds": ["statute"],
        "article_refs": [],
    }


def real(case_id="r1", **over):
    d = {
        "kind": "real",
        "gold_version": 2,
        "case_id": case_id,
        "reviewed": {"by": None, "date": None},
        "oa_id": "9-9-9999-000001",
        "rejection": 1,
        "question": question(),
        "expect_sources": [
            {
                "source_kind": "statute",
                "identifier": "가짜법 제1조제2항",
                "document_id": "가짜법_000001_20200101",
                "loc": 100200,
                "edition_status": "confirmed",
            }
        ],
    }
    d.update(over)
    return d


def source(kind="statute", text_kind=None, doc="가짜법_000001_20200101", status="confirmed"):
    s = {
        "source_kind": kind,
        "identifier": "가짜 식별자",
        "evidence": {"document_id": doc, "raw_text": "지어낸 원문", "edition": "20200101"},
        "status": {"value": status, "checked": "원문 대조"}
        if status == "confirmed"
        else {"value": status, "reason": "edition_unknown"},
    }
    if kind in ("precedent", "trial"):
        s.update(text_kind=text_kind or "summary", speaker="court")
    return s


def bundle(src, as_of="2020-01-01"):
    return {
        "status": src["status"],
        "bundle_id": "b1",
        "oa_id": "9-9-9999-000001",
        "rejection": 1,
        "question": question(as_of),
        "checked_on": "2020-02-01",
        "claims": [
            {
                "status": src["status"],
                "no": 1,
                "text": "지어낸 주장",
                "sources": [src],
                "flags": ["needs_human_review"],
            }
        ],
    }


def injected(error, case_id=None, **over):
    src, fix, as_of = source(), None, "2020-01-01"
    if error == "summary_as_full":
        src = source("precedent", "full", doc="가짜판례_1")
        fix = {"text_kind": "summary"}
    elif error == "old_deadline_as_current":
        as_of = None
        fix = {"document_id": "가짜규칙_000002", "raw_text_contains": "지어낸 기한"}
    elif error == "other_edition_asserted":
        fix = {"document_id": "가짜법_000001_20180101"}
    d = {
        "kind": "injected",
        "gold_version": 2,
        "case_id": case_id or f"i-{error}",
        "reviewed": {"by": None, "date": None},
        "error": error,
        "base_case_id": "r1",
        "bundle": bundle(src, as_of),
        "target_claim": 1,
        "target_source": 0,
        "fix": fix,
    }
    d.update(over)
    return d


def write(tmp_path, rows, raw=None):
    p = tmp_path / "evidence_cases.jsonl"
    p.write_text(raw if raw is not None else "\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def load_one(tmp_path, row):
    if row["kind"] == "injected" and row.get("base_case_id") == "r1":
        return load_f2_cases(write(tmp_path, [real("r1"), row]), 2)[1]  # 바탕 사례를 같이 둠
    return load_f2_cases(write(tmp_path, [row]), 2)[0]


# ---- 읽기 ----
def test_맞는_사례는_종류별로_읽힌다(tmp_path):
    rows = [real()] + [injected(e) for e in ERRORS]
    cases = load_f2_cases(write(tmp_path, rows), 2)
    assert isinstance(cases[0], RealCase)
    assert all(isinstance(c, InjectedCase) for c in cases[1:])
    assert len(cases) == 6


def test_빈_줄은_건너뛴다(tmp_path):
    p = write(tmp_path, [], raw=json.dumps(real()) + "\n\n  \n" + json.dumps(real("r2")) + "\n")
    assert len(load_f2_cases(p, 2)) == 2


def test_파일이_없으면_NoGold(tmp_path):
    with pytest.raises(NoGold):
        load_f2_cases(tmp_path / "없음.jsonl", 2)


def test_0줄이면_NoGold(tmp_path):
    with pytest.raises(NoGold):
        load_f2_cases(write(tmp_path, [], raw="\n\n"), 2)


def test_NoGold는_EvalError다():
    assert issubclass(NoGold, EvalError)


def test_JSON_문법이_틀리면_줄_번호만_말한다(tmp_path):
    p = write(tmp_path, [], raw=json.dumps(real()) + "\n{지어낸깨진글자\n")
    with pytest.raises(EvalError) as e:
        load_f2_cases(p, 2)
    assert "2번째 줄" in str(e.value)
    assert "지어낸깨진글자" not in str(e.value)


def test_gold_version이_다르면_멈춘다(tmp_path):
    with pytest.raises(EvalError, match="gold_version"):
        load_f2_cases(write(tmp_path, [real(gold_version=1)]), 2)


def test_case_id가_겹치면_멈춘다(tmp_path):
    with pytest.raises(EvalError, match="case_id"):
        load_f2_cases(write(tmp_path, [real("x"), real("x")]), 2)


def test_case_id가_비면_멈춘다(tmp_path):
    with pytest.raises(EvalError):
        load_one(tmp_path, real(case_id=" "))


def test_모르는_칸은_멈추고_값_글자는_메시지에_없다(tmp_path):
    row = real(몰래칸="지어낸비밀값")
    with pytest.raises(EvalError) as e:
        load_one(tmp_path, row)
    assert "1번째 줄" in str(e.value)
    assert "extra_forbidden" in str(e.value)
    assert "지어낸비밀값" not in str(e.value)


def test_kind가_없거나_모르면_멈춘다(tmp_path):
    row = real()
    row["kind"] = "엉뚱"
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


# ---- 실제 질문 ----
def test_expect_sources가_비면_멈춘다(tmp_path):
    with pytest.raises(EvalError):
        load_one(tmp_path, real(expect_sources=[]))


def test_실제_질문은_as_of가_필수(tmp_path):
    with pytest.raises(EvalError):
        load_one(tmp_path, real(question=question(as_of=None)))


def test_실제_질문의_source는_oa_rejection(tmp_path):
    q = question()
    q["source"] = "user_question"
    with pytest.raises(EvalError):
        load_one(tmp_path, real(question=q))


def test_edition_status_값은_둘만(tmp_path):
    row = real()
    row["expect_sources"][0]["edition_status"] = "엉뚱"
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


def test_loc은_null이어도_된다(tmp_path):
    row = real()
    row["expect_sources"][0]["loc"] = None
    assert load_one(tmp_path, row).expect_sources[0].loc is None


def test_rejection은_1_이상(tmp_path):
    with pytest.raises(EvalError):
        load_one(tmp_path, real(rejection=0))


# ---- 오류 주입 ----
@pytest.mark.parametrize("error", ERRORS)
def test_5종_모두_맞는_모양이면_통과(tmp_path, error):
    assert load_one(tmp_path, injected(error)).error == error


def test_모르는_error_종류는_멈춘다(tmp_path):
    row = injected("nonexistent_source")
    row["error"] = "엉뚱"
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


def test_target_claim이_bundle에_없으면_멈춘다(tmp_path):
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("nonexistent_source", target_claim=7))


def test_target_source가_범위_밖이면_멈춘다(tmp_path):
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("nonexistent_source", target_source=1))


def test_target_근거가_confirmed가_아니면_멈춘다(tmp_path):
    row = injected("nonexistent_source")
    row["bundle"] = bundle(source(status="unverified"))
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


def test_bundle이_core_스키마를_어기면_멈춘다(tmp_path):
    row = injected("nonexistent_source")
    row["bundle"]["claims"][0]["flags"] = []  # review도 없고 flag도 없음
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


def test_bundle에_review가_있으면_멈춘다(tmp_path):
    row = injected("nonexistent_source")
    row["bundle"]["claims"][0]["review"] = {"verdict": "supported", "reason": "지어낸 이유"}
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


def test_fix가_있어도_칸이_모두_null이면_멈춘다(tmp_path):
    row = injected("other_edition_asserted", fix={"document_id": None})
    with pytest.raises(EvalError):
        load_one(tmp_path, row)


def test_없는_출처와_불일치는_fix가_null이어야(tmp_path):
    for e in ("nonexistent_source", "claim_text_mismatch"):
        with pytest.raises(EvalError):
            load_one(tmp_path, injected(e, fix={"identifier": "가짜 식별자"}))


def test_요지를_전문으로_쓴_사례는_판례나_심결의_full이고_fix는_summary(tmp_path):
    # 법령 근거면 안 됨
    row = injected("summary_as_full")
    row["bundle"] = bundle(source("statute"))
    with pytest.raises(EvalError):
        load_one(tmp_path, row)
    # target이 summary이면 안 됨
    row = injected("summary_as_full")
    row["bundle"] = bundle(source("trial", "summary"))
    with pytest.raises(EvalError):
        load_one(tmp_path, row)
    # fix.text_kind가 summary가 아니면 안 됨
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("summary_as_full", fix={"text_kind": "full"}))
    # fix가 없으면 안 됨
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("summary_as_full", fix=None))


def test_개정_전_기한은_현행_질문이고_fix에_문서와_글이_둘_다(tmp_path):
    # as_of가 있으면 현행 질문이 아님
    row = injected("old_deadline_as_current")
    row["bundle"] = bundle(source(), as_of="2020-01-01")
    with pytest.raises(EvalError):
        load_one(tmp_path, row)
    for fix in ({"document_id": "가짜규칙_000002"}, {"raw_text_contains": "지어낸 기한"}, None):
        with pytest.raises(EvalError):
            load_one(tmp_path, injected("old_deadline_as_current", fix=fix))


def test_다른_판본_단정은_fix_문서가_있고_target_문서와_달라야(tmp_path):
    same = {"document_id": "가짜법_000001_20200101"}  # target 근거와 같은 문서
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("other_edition_asserted", fix=same))
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("other_edition_asserted", fix={"identifier": "가짜 식별자"}))
    with pytest.raises(EvalError):
        load_one(tmp_path, injected("other_edition_asserted", fix=None))


def test_base_case_id는_null이어도_된다(tmp_path):
    assert (
        load_one(tmp_path, injected("nonexistent_source", base_case_id=None)).base_case_id is None
    )


# ---- 세트 크기 ----
def full_set(per_error=4, reals=1):
    rows = [real(f"r{i}") for i in range(1, reals + 1)]  # r1은 주입 사례의 바탕
    for e in ERRORS:
        rows += [injected(e, f"{e}-{i}") for i in range(per_error)]
    return rows


def test_셈은_real_수와_종류별_수와_합계(tmp_path):
    cases = load_f2_cases(write(tmp_path, full_set()), 2)
    c = count_cases(cases)
    assert c["real"] == 1
    assert c["total"] == 21
    assert all(c[e] == 4 for e in ERRORS)


def test_세트가_기준_이상이면_통과(tmp_path):
    check_set_size(load_f2_cases(write(tmp_path, full_set()), 2))  # 21개, 종류마다 4개


def test_합계가_모자라면_멈춘다(tmp_path):
    cases = load_f2_cases(write(tmp_path, full_set(per_error=3)), 2)  # 16개
    with pytest.raises(EvalError, match="20"):
        check_set_size(cases)


def test_한_종류가_비면_멈춘다(tmp_path):
    rows = [real(f"r{i}") for i in range(1, 11)]
    for e in ERRORS[:4]:
        rows += [injected(e, f"{e}-{i}") for i in range(4)]
    cases = load_f2_cases(write(tmp_path, rows), 2)  # 26개지만 old_deadline 0
    with pytest.raises(EvalError, match="old_deadline_as_current"):
        check_set_size(cases)


# ---- CLI ----
def test_CLI_통과하면_셈을_찍고_0(tmp_path, capsys):
    p = write(tmp_path, full_set())
    assert main(["--check", str(p), "--version", "2"]) == 0
    assert "21" in capsys.readouterr().out


def test_CLI_실패하면_이유를_찍고_1(tmp_path, capsys):
    p = write(tmp_path, [real(gold_version=1)])
    assert main(["--check", str(p), "--version", "2"]) == 1
    assert "gold_version" in capsys.readouterr().out


def test_CLI_세트가_모자라면_1(tmp_path):
    assert main(["--check", str(write(tmp_path, [real()])), "--version", "2"]) == 1


def test_CLI_파일이_없으면_1(tmp_path):
    assert main(["--check", str(tmp_path / "없음.jsonl"), "--version", "2"]) == 1


# ---- 오류 이유 글 ----
def test_value_error는_이유_문구까지_메시지에_싣는다(tmp_path):
    row = injected("nonexistent_source", target_claim=7)
    with pytest.raises(EvalError, match="target_claim이 bundle 주장에 없음"):
        load_one(tmp_path, row)


def test_value_error_문구에_입력_값이_끼면_문구를_빼고_값을_싣지_않는다(tmp_path):
    # core 스키마 unit_id 꼴 검사는 입력 값을 문구에 넣는다 → 그 글자가 메시지에 새면 안 된다
    row = injected("nonexistent_source")
    row["bundle"]["unit_id"] = "비공개표식-XYZ"
    with pytest.raises(EvalError) as e:
        load_one(tmp_path, row)
    assert "비공개표식-XYZ" not in str(e.value)
    assert "unit_id: value_error" in str(e.value)


def test_fix_규칙_위반은_이유를_말한다(tmp_path):
    with pytest.raises(EvalError, match="fix가 null"):
        load_one(tmp_path, injected("claim_text_mismatch", fix={"identifier": "가짜 식별자"}))


# ---- 줄 사이 검사 (base_case_id) ----
def test_base_case_id가_파일_안_real을_가리키면_통과(tmp_path):
    rows = [real("r1"), injected("nonexistent_source")]  # base_case_id = r1, oa_id 같음
    assert len(load_f2_cases(write(tmp_path, rows), 2)) == 2


def test_base_case_id가_없는_사례를_가리키면_멈춘다(tmp_path):
    rows = [real("r1"), injected("nonexistent_source", base_case_id="없는사례")]
    with pytest.raises(EvalError, match="base_case_id"):
        load_f2_cases(write(tmp_path, rows), 2)


def test_base_case_id가_injected를_가리키면_멈춘다(tmp_path):
    rows = [
        real("r1"),
        injected("nonexistent_source", "i1"),
        injected("claim_text_mismatch", "i2", base_case_id="i1"),
    ]
    with pytest.raises(EvalError, match="base_case_id"):
        load_f2_cases(write(tmp_path, rows), 2)


def test_bundle_oa_id가_바탕_사례와_다르면_멈춘다(tmp_path):
    rows = [real("r1", oa_id="9-9-9999-000777"), injected("nonexistent_source")]
    with pytest.raises(EvalError, match="oa_id"):
        load_f2_cases(write(tmp_path, rows), 2)


def test_바탕_사례가_뒷줄에_있어도_통과(tmp_path):
    rows = [injected("nonexistent_source"), real("r1")]
    assert len(load_f2_cases(write(tmp_path, rows), 2)) == 2


def test_입력_dict는_검사가_바꾸지_않는다(tmp_path):
    row = injected("nonexistent_source")
    before = copy.deepcopy(row)
    load_one(tmp_path, row)
    assert row == before
