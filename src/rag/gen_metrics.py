"""생성 평가 지표(순수 함수). 정답이 문장이 아니라서 코드로 셀 수 있는 것만 센다.

rows 의 각 항목: {"id", "gold": [코퍼스 형식 조문 id], "result": answer_question 결과}.
- 정답 있음: 정답 조문을 인용했는가(cited_gold), status 분포, 검증 경고 수.
  부분 답변 질문도 정답 있음의 일부이며 partial/answered 둘 다 오답으로 세지 않는다(no_basis 만 잘못된 답, spec 10장 1번).
- 정답 없음: no_basis 로 답했는가, 답을 만들어 냈는가(answered/partial).
"""
import re

_POLITE_END = re.compile(r"(습니다|ㅂ니다|니다|세요|어요|아요|에요|예요|해요|죠|네요)[.!?)\]]*\s*$")
_PLAIN_END = re.compile(r"(한다|있다|없다|된다|이다|않다|난다|받는다|본다|낸다|진다|있음|없음|함|됨)[.]?[)\]]*\s*$")
LIST_CHECKS = ("unknown_tags", "articles_outside_evidence", "numbers_not_in_evidence")


def is_mostly_plain_style(answer: str) -> bool:
    """답변의 문장 끝으로 반말체(~한다, ~있다)가 존댓말보다 많은지 본다. 추정이며(문장 끝 규칙), 말투 점검용 보조 지표다."""
    plain = polite = 0
    for line in answer.split("\n"):
        line = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line.strip()).replace("**", "").strip()
        if len(line) <= 12:
            continue
        polite += bool(_POLITE_END.search(line))
        plain += bool(_PLAIN_END.search(line))
    return plain > polite


def _failed(checks: dict) -> dict[str, bool]:
    out = {k: bool(checks.get(k)) for k in LIST_CHECKS}
    out["status_cited_mismatch"] = bool(checks.get("status_cited_mismatch"))
    return out


def summarize_answerable(rows: list[dict]) -> dict:
    s = {"n": len(rows), "cited_gold": 0, "answered": 0, "partial": 0, "no_basis": 0, "error": 0,
         "check_failures": 0, "plain_style": 0, "by_check": {k: 0 for k in (*LIST_CHECKS, "status_cited_mismatch")}}
    for r in rows:
        res = r["result"]
        s[res["status"]] += 1
        if res["status"] in ("answered", "partial") and set(r["gold"]) & set(res["cited_articles"]):  # 근거 없음이라 해 놓고 인용이 남은 것은 적중이 아님
            s["cited_gold"] += 1
        s["plain_style"] += is_mostly_plain_style(res.get("answer", ""))
        failed = _failed(res["checks"])
        s["check_failures"] += any(failed.values())
        for k, v in failed.items():
            s["by_check"][k] += v
    return s


def summarize_noanswer(rows: list[dict]) -> dict:
    fabricated = [r["id"] for r in rows if r["result"]["status"] in ("answered", "partial")]
    return {"n": len(rows), "no_basis": sum(r["result"]["status"] == "no_basis" for r in rows),
            "fabricated": len(fabricated), "fabricated_ids": fabricated,
            "answered": sum(r["result"]["status"] == "answered" for r in rows),
            "partial": sum(r["result"]["status"] == "partial" for r in rows),
            "error": sum(r["result"]["status"] == "error" for r in rows)}
