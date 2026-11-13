import pytest
import json

from src.rag.ask import answer_question
from src.rag.evidence import Evidence
from src.rag.pipeline import Retrieval
from src.rag.settings import Settings


def make_retrieval(q="질문"):
    ev = [Evidence("E1", "특허법#제29조", "특허법 제29조", "12개월 이내 본문", False),
          Evidence("E2", "특허법 시행령#제5조", "특허법 시행령 제5조", "시행령 본문", True)]
    return Retrieval(q, q + "\n용어", "용어", ["용어"], [e.article_id for e in ev], "1,2", ev)


class FakePipeline:
    def __init__(self):
        self.calls = 0

    def retrieve(self, q):
        self.calls += 1
        return make_retrieval(q)


def fake_generate(status="answered", answer="12개월 이내입니다 [E1]", cited=("E1",)):
    def gen(question, evidence, model, key, max_tokens):
        return {"status": status, "answer": answer, "cited": list(cited), "raw": "RAW"}
    return gen


def test_answer_question_assembles_result_and_converts_tags():
    r = answer_question("질문", FakePipeline(), Settings(), "SECRET", generate_fn=fake_generate(cited=("E2",)))
    assert r["status"] == "answered" and r["cited"] == ["E2"]
    assert r["cited_articles"] == ["특허법 시행령#제5조"]
    assert r["evidence"][1] == {"tag": "E2", "article_id": "특허법 시행령#제5조", "label": "특허법 시행령 제5조",
                                "truncated": True}
    assert "text" not in r["evidence"][0]
    assert r["retrieval"]["ranked"] == ["특허법#제29조", "특허법 시행령#제5조"] and r["retrieval"]["terms"] == ["용어"]
    assert (r["generation"]["model"], r["generation"]["raw"]) == (Settings().generation_model, "RAW")
    assert r["generation"]["prompt_version"] == "v3" and r["generation"]["prompt_sha256"]
    assert set(r["seconds"]) == {"retrieval", "generation"} and r["checks"]["unknown_tags"] == []


def test_unknown_tag_is_dropped_from_cited_articles_but_flagged_in_checks():
    r = answer_question("질문", FakePipeline(), Settings(), "k", generate_fn=fake_generate(cited=("E1", "E9")))
    assert r["cited_articles"] == ["특허법#제29조"] and r["checks"]["unknown_tags"] == ["E9"]


def test_given_retrieval_skips_pipeline_and_records_zero_retrieval_time():
    p = FakePipeline()
    r = answer_question("질문", p, Settings(), "k", retrieval=make_retrieval(), generate_fn=fake_generate())
    assert p.calls == 0 and r["seconds"]["retrieval"] == 0.0


def test_result_never_contains_api_key():
    r = answer_question("질문", FakePipeline(), Settings(), "SECRET-KEY", generate_fn=fake_generate())
    assert "SECRET-KEY" not in json.dumps(r, ensure_ascii=False)


def test_no_basis_with_leftover_citation_sets_mismatch_flag():
    r = answer_question("질문", FakePipeline(), Settings(), "k",
                        generate_fn=fake_generate(status="no_basis", answer="근거를 찾지 못했습니다", cited=("E1",)))
    assert r["checks"]["status_cited_mismatch"] is True


def test_default_generation_uses_adopted_prompt_version_and_records_it(monkeypatch):
    import hashlib

    from src.rag import ask as ask_mod
    from src.rag.generate import PROMPTS

    assert Settings().prompt_version == "v3"
    seen = {}

    def spy(question, evidence, model, key, max_tokens, version="v1"):
        seen["version"] = version
        return {"status": "answered", "answer": "답 [E1]", "cited": ["E1"], "raw": "RAW"}

    monkeypatch.setattr(ask_mod, "generate", spy)
    r = answer_question("질문", FakePipeline(), Settings(), "k")  # generate_fn 을 안 주면 설정의 프롬프트 버전을 쓴다
    assert seen["version"] == "v3"
    assert r["generation"]["prompt_version"] == "v3"
    assert r["generation"]["prompt_sha256"] == hashlib.sha256(PROMPTS["v3"].encode("utf-8")).hexdigest()[:16]


def test_result_has_display_answer_and_clickable_citations():
    r = answer_question("질문", FakePipeline(), Settings(), "k",
                        generate_fn=fake_generate(answer="12개월 이내입니다(특허법 제29조, E1). 시행령은 E2에 있습니다.", cited=("E1", "E2")))
    assert r["answer"].count("E1") == 1  # 원래 답변은 그대로 보존
    assert r["answer_display"] == "12개월 이내입니다(특허법 제29조). 시행령은 특허법 시행령 제5조에 있습니다."
    assert r["citations"] == [{"article_id": "특허법#제29조", "label": "특허법 제29조"},
                              {"article_id": "특허법 시행령#제5조", "label": "특허법 시행령 제5조"}]


# ---- 작은 지적 정리(M7): CLI 오류는 한 줄과 종료 코드 1 ----
def test_cli_reports_errors_in_one_line_with_exit_code_1(monkeypatch, capsys):
    from src.rag import ask as ask_mod

    def boom(settings):
        raise RuntimeError("생성 호출 실패: HTTP 500 서버 오류")

    monkeypatch.setattr(ask_mod, "build_pipeline", boom)
    assert ask_mod.main(["질문"]) == 1
    err = capsys.readouterr().err
    assert "오류" in err and "HTTP 500" in err and "Traceback" not in err and err.count("\n") == 1


def test_cli_missing_env_file_gives_a_clear_message(monkeypatch, capsys):
    from src.rag import ask as ask_mod

    def missing(settings):
        raise FileNotFoundError(2, "No such file", ".env")

    monkeypatch.setattr(ask_mod, "build_pipeline", missing)
    assert ask_mod.main(["질문"]) == 1
    assert ".env" in capsys.readouterr().err


def test_cli_debug_flag_shows_the_full_traceback(monkeypatch):
    from src.rag import ask as ask_mod

    def boom(settings):
        raise RuntimeError("자세히 보고 싶은 오류")

    monkeypatch.setattr(ask_mod, "build_pipeline", boom)
    with pytest.raises(RuntimeError):
        ask_mod.main(["질문", "--debug"])


def test_result_usage_merges_retrieval_and_generation_tokens():
    from src.retrieval import usage

    ret = make_retrieval()
    ret.usage = usage.summarize([{"stage": "expand", "model": "gpt-x", "input_tokens": 100, "output_tokens": 10},
                                 {"stage": "rerank", "model": "gpt-x", "input_tokens": 2000, "output_tokens": 40}])

    def gen(question, evidence, model, key, max_tokens):
        usage.record("generate", "claude-y", 900, 200)
        return {"status": "answered", "answer": "답 [E1]", "cited": ["E1"], "raw": "RAW"}

    r = answer_question("질문", FakePipeline(), Settings(), "k", retrieval=ret, generate_fn=gen)  # 캐시된 검색 결과도 검색 사용량을 가져온다
    u = r["usage"]
    assert u["by_stage"]["generate:claude-y"]["input_tokens"] == 900 and u["by_stage"]["expand:gpt-x"]["calls"] == 1
    assert (u["input_tokens"], u["output_tokens"]) == (3000, 250)
