import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.rag.evidence import Evidence
from src.rag.pipeline import Retrieval

spec = importlib.util.spec_from_file_location("run_generation_eval", Path("scripts/run_generation_eval.py"))
rge = importlib.util.module_from_spec(spec)
sys.modules["run_generation_eval"] = rge
spec.loader.exec_module(rge)


def qline(i, split, gold, note=""):
    return json.dumps({"id": i, "split": split, "law": "특허법" if gold else "", "question": f"질문 {i}", "gold": gold,
                       "note": note}, ensure_ascii=False)


@pytest.fixture
def files(tmp_path):
    dev = tmp_path / "q_dev.jsonl"
    dev.write_text("\n".join([qline("N1", "dev2", ["특허법#제29조"]), qline("N2", "dev2", ["특허법#제30조"], "부분 답변")]) + "\n",
                   encoding="utf-8")
    na = tmp_path / "q_noanswer.jsonl"
    na.write_text("\n".join([qline("S1", "dev2", []), qline("S2", "sealed2", [])]) + "\n", encoding="utf-8")
    return dev, na, tmp_path / "out"


class FakePipeline:
    def __init__(self):
        self.calls = []

    def retrieve(self, q):
        self.calls.append(q)
        ev = [Evidence("E1", "특허법#제29조", "특허법 제29조", "12개월 본문", False)]
        return Retrieval(q, q, "raw", [], ["특허법#제29조"], "1", ev)


def gen_ok(question, evidence, model, key, max_tokens):
    if question.startswith("질문 S"):
        return {"status": "no_basis", "answer": "근거를 찾지 못했습니다", "cited": [], "raw": "r"}
    return {"status": "answered", "answer": "12개월 [E1]", "cited": ["E1"], "raw": "r"}


def run(files, extra=(), pipeline=None, gen=gen_ok):
    dev, na, out = files
    p = pipeline or FakePipeline()
    rc = rge.main(["--questions", str(dev), "--noanswer", str(na), "--out-dir", str(out), *extra],
                  pipeline=p, generate_fn=gen, anthropic_key="SECRET-KEY")
    return rc, p, out


def test_script_refuses_sealed_without_flag(tmp_path):
    with pytest.raises(SystemExit):
        rge.main(["--questions", "data/eval/questions_d2_sealed.jsonl", "--out-dir", str(tmp_path)],
                 pipeline=FakePipeline(), generate_fn=gen_ok, anthropic_key="k")


def test_script_writes_result_without_key_and_uses_only_matching_noanswer_split(files):
    rc, p, out = run(files)
    assert rc == 0
    f = next(out.glob("gen_*.json"))
    text = f.read_text(encoding="utf-8")
    assert "SECRET-KEY" not in text
    d = json.loads(text)
    assert d["summary_answerable"]["n"] == 2 and d["summary_noanswer"]["n"] == 1  # dev2 만 (sealed2 제외)
    assert sorted(p.calls) == ["질문 N1", "질문 N2", "질문 S1"]
    assert d["config"]["generation_model"] and d["config"]["prompt_sha256"]
    assert d["mean_seconds"]["retrieval"] is not None  # 실시간 검색 시간이 기록됨
    assert next(out.glob("gen_*.md")).read_text(encoding="utf-8").count("질문 N2") >= 1  # 부분 답변 질문은 표본에 항상 포함


def test_retrieval_cache_is_written_then_reused(files, tmp_path):
    cache = tmp_path / "cache.json"
    run(files, ["--retrieval-cache", str(cache)])
    assert cache.exists()
    before = cache.read_text(encoding="utf-8")
    rc, p2, _ = run(files, ["--retrieval-cache", str(cache), "--out-dir", str(tmp_path / "out2")])
    assert p2.calls == [] and cache.read_text(encoding="utf-8") == before


def test_cache_miss_is_an_error_unless_allowed_and_never_overwrites(files, tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"meta": {}, "items": {}}), encoding="utf-8")
    p0 = FakePipeline()
    with pytest.raises(SystemExit):
        run(files, ["--retrieval-cache", str(cache)], pipeline=p0)
    assert p0.calls == []  # 검색을 시작하기 전에 멈춘다
    _, p, out = run(files, ["--retrieval-cache", str(cache), "--allow-cache-miss"])
    assert len(p.calls) == 3 and json.loads(cache.read_text(encoding="utf-8")) == {"meta": {}, "items": {}}
    rows = json.loads(next(out.glob("gen_*.json")).read_text(encoding="utf-8"))["answerable"]
    assert all(r["retrieval_from_cache"] is False for r in rows)


def test_one_failing_question_is_recorded_as_error_and_run_continues(files):
    def flaky(question, evidence, model, key, max_tokens):
        if question == "질문 N1":
            raise RuntimeError("생성 호출 실패: HTTP 500")
        return gen_ok(question, evidence, model, key, max_tokens)

    rc, _, out = run(files, gen=flaky)
    d = json.loads(next(out.glob("gen_*.json")).read_text(encoding="utf-8"))
    assert rc == 0 and d["summary_answerable"]["error"] == 1 and d["summary_answerable"]["n"] == 2


def test_limit_restricts_questions(files):
    _, p, _ = run(files, ["--limit", "1"])
    assert sorted(p.calls) == ["질문 N1", "질문 S1"]


def test_prompt_version_is_recorded_in_config(files):
    _, _, out1 = run(files)
    d1 = json.loads(next(out1.glob("gen_*.json")).read_text(encoding="utf-8"))
    dev, na, out2 = files
    rge.main(["--questions", str(dev), "--noanswer", str(na), "--out-dir", str(out2.parent / "out_v1"),
              "--prompt-version", "v1"], pipeline=FakePipeline(), generate_fn=gen_ok, anthropic_key="k")
    d2 = json.loads(next((out2.parent / "out_v1").glob("gen_*.json")).read_text(encoding="utf-8"))
    assert d1["config"]["prompt_version"] == "v3" and d2["config"]["prompt_version"] == "v1"  # 기본값은 채택된 v3
    assert d1["config"]["prompt_sha256"] != d2["config"]["prompt_sha256"]


def test_questions_file_with_sealed_split_rows_is_refused_without_flag(files, tmp_path):
    _, na, out = files  # 정답 없음 파일에는 sealed2 행이 섞여 있다: 이것을 --questions 로 주면 우회가 된다
    p = FakePipeline()
    with pytest.raises(SystemExit):
        rge.main(["--questions", str(na), "--out-dir", str(out)], pipeline=p, generate_fn=gen_ok, anthropic_key="k")
    assert p.calls == []


def test_noanswer_path_named_sealed_is_refused_without_flag(files, tmp_path):
    dev, na, out = files
    sealed_na = tmp_path / "q_sealed_noanswer.jsonl"
    sealed_na.write_text(na.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(SystemExit):
        rge.main(["--questions", str(dev), "--noanswer", str(sealed_na), "--out-dir", str(out)],
                 pipeline=FakePipeline(), generate_fn=gen_ok, anthropic_key="k")


def test_cache_is_saved_with_meta_and_rejected_when_settings_or_question_text_differ(files, tmp_path):
    cache = tmp_path / "cache.json"
    run(files, ["--retrieval-cache", str(cache)])
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["meta"]["n_evidence"] == 5 and saved["meta"]["max_evidence_chars"] == 4000 and "N1" in saved["items"]
    changed = {**saved, "meta": {**saved["meta"], "n_evidence": 3}}  # 다른 설정으로 만든 캐시
    cache2 = tmp_path / "cache2.json"
    cache2.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit):
        run(files, ["--retrieval-cache", str(cache2), "--out-dir", str(tmp_path / "o2")])
    stale = json.loads(cache.read_text(encoding="utf-8"))
    stale["items"]["N1"]["question"] = "고쳐지기 전 질문 문장"  # 같은 id, 다른 문장
    cache3 = tmp_path / "cache3.json"
    cache3.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit):
        run(files, ["--retrieval-cache", str(cache3), "--out-dir", str(tmp_path / "o3")])


def test_cache_creation_never_overwrites_a_file_created_meanwhile(files, tmp_path):
    cache = tmp_path / "cache.json"

    class Racing(FakePipeline):
        def retrieve(self, q):
            cache.write_text("다른 실행이 먼저 만든 캐시", encoding="utf-8")  # 실행 도중 같은 경로에 파일이 생김
            return super().retrieve(q)

    with pytest.raises(SystemExit):
        run(files, ["--retrieval-cache", str(cache)], pipeline=Racing())
    assert cache.read_text(encoding="utf-8") == "다른 실행이 먼저 만든 캐시"


def test_failed_retrieval_prevents_saving_an_incomplete_cache(files, tmp_path):
    cache = tmp_path / "cache.json"

    class Flaky(FakePipeline):
        def retrieve(self, q):
            if q == "질문 N2":
                raise RuntimeError("검색 실패")
            return super().retrieve(q)

    run(files, ["--retrieval-cache", str(cache)], pipeline=Flaky())
    assert not cache.exists()  # 일부만 든 캐시를 저장하면 다음 실행이 조용히 다른 검색을 섞는다


def test_http_401_body_is_not_written_to_error_field(files):
    def leaky(question, evidence, model, key, max_tokens):
        raise RuntimeError("임베딩 호출 실패: HTTP 401 Incorrect API key provided: sk-proj-****abcd")

    _, _, out = run(files, gen=leaky)
    text = next(out.glob("gen_*.json")).read_text(encoding="utf-8")
    assert "sk-proj" not in text and "HTTP 401" in text


def test_limit_zero_runs_nothing(files):
    _, p, out = run(files, ["--limit", "0"])
    assert p.calls == []
    d = json.loads(next(out.glob("gen_*.json")).read_text(encoding="utf-8"))
    assert d["summary_answerable"]["n"] == 0 and d["summary_noanswer"]["n"] == 0


def test_summary_for_partial_flagged_questions_is_reported_separately(files):
    _, _, out = run(files)  # N2 는 note 에 "부분 답변"이 있다
    d = json.loads(next(out.glob("gen_*.json")).read_text(encoding="utf-8"))
    s = d["summary_partial_flagged"]
    assert s["n"] == 1 and s["answered"] == 1 and s["cited_gold"] in (0, 1)
