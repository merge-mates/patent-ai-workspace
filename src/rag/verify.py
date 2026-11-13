"""답변 검증(순수 함수). 실패해도 답을 막지 않고 표시만 한다 — 평가와 화면이 이 표시를 쓴다.

검사 4가지(spec 4장): 없는 꼬리표 인용, 근거 밖 조문 언급, 근거 본문에 없는 숫자, 상태와 인용의 모순.
한계: 숫자는 아라비아 숫자만 본다("삼십일" 같은 한글 숫자·단위는 비교하지 않음).
"""
import re

from src.rag.evidence import Evidence

# 조문 번호: 띄어 쓴 표기("제 47 조")도 같은 조문으로 본다. 가지 번호("제47조의2")는 붙여 쓴 것만 인정한다
# ("제61조의 3가지 유형"의 "의"는 조사라서 띄어 쓴 숫자를 가지 번호로 읽으면 오경보가 난다)
_ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:의(\d+))?")
# 숫자 검사에서 뺄 것: 조·항·호·목 번호와 E1 같은 꼬리표("E1에"처럼 한글 조사가 붙은 것 포함)
_NON_QUANTITY = re.compile(r"제\s*\d+\s*(?:조(?:의\d+)?|항|호|목)|(?<![A-Za-z0-9])E\d+(?![0-9A-Za-z])")
# 목록 번호("5. 국제특허출원은…")는 수치가 아니다: 줄 맨 앞의 번호, 또는 줄 중간에서 뒤에 숫자가 아닌 글이 오는 1~2자리 번호
_LINE_MARKER = re.compile(r"(?m)^\s*\d{1,2}\.\s+")
_INLINE_MARKER = re.compile(r"(?<=[\s)])\d{1,2}\.(?=\s+[^\s\d])")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")  # "1,000" 을 한 숫자 1000 으로


def _article_key(m: re.Match) -> str:
    return f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


def _unique(items):
    return list(dict.fromkeys(items))


def _answer_numbers(answer: str) -> list[str]:
    text = _THOUSANDS.sub("", _NON_QUANTITY.sub(" ", answer))
    text = _INLINE_MARKER.sub(" ", _LINE_MARKER.sub(" ", text))
    return re.findall(r"\d+", text)


def check_answer(status: str, answer: str, cited: list[str], evidence: list[Evidence]) -> dict:
    tags = {e.tag for e in evidence}
    # 근거 조문 자신의 번호 + 근거 본문이 인용하는 조문(예: 제30조 본문의 "제29조제1항")은 근거 안으로 본다.
    # 실제 개발 평가에서 본문 속 인용을 답변이 되풀이한 경우가 전부 오경보였다.
    evidence_articles = {_article_key(m) for e in evidence for m in _ARTICLE.finditer(e.article_id + "\n" + e.text)}
    evidence_numbers = {n for e in evidence for n in re.findall(r"\d+", _THOUSANDS.sub("", e.text))}

    mentioned = [_article_key(m) for m in _ARTICLE.finditer(answer)]
    return {
        "unknown_tags": [t for t in cited if t not in tags],
        "articles_outside_evidence": _unique(a for a in mentioned if a not in evidence_articles),
        "numbers_not_in_evidence": _unique(n for n in _answer_numbers(answer) if n not in evidence_numbers),
        # error(파싱 실패)는 답이 없는 상태라 인용이 비는 것이 당연하므로 모순으로 세지 않는다
        "status_cited_mismatch": status in ("answered", "partial", "no_basis") and (status == "no_basis") == bool(cited),
    }
