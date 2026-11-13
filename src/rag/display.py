"""화면 표시용: 답변 속 꼬리표(E1, E2, …)를 사용자가 알아볼 수 있는 조문 이름으로 바꾼다.

모델은 근거 조문을 꼬리표로 인용한다(법령 이름이 겹쳐도 틀리지 않게). 사용자에게는 꼬리표가 의미가 없으므로
화면에 보여 주기 직전에 이 함수로 치환한다. 규칙(결정적, 모델 호출 없음):
- 괄호 안에 이미 조문("제30조")이 있으면 꼬리표만 지운다: "(특허법 제30조제1항, E1)" -> "(특허법 제30조제1항)"
- 꼬리표만 있으면 조문 이름으로 바꾼다: "(E3 ①②)" -> "(특허법 제81조 ①②)"
- 괄호 밖 꼬리표도 이름으로("E1에" -> "특허법 제30조에"), 근거에 없는 꼬리표는 지운다.
"""
import re

_TAG = re.compile(r"(?<![A-Za-z0-9])E(\d+)(?![0-9A-Za-z])")  # 한글 조사(E1에)는 꼬리표, 영문자·숫자가 붙으면(E1x, E12 의 일부) 아님
_GROUP = re.compile(r"([(\[])([^()\[\]\n]*)([)\]])")
_ARTICLE = re.compile(r"제\d+조")


def render_answer(answer: str, evidence: list[dict]) -> str:
    """answer: 모델 답변 글, evidence: [{"tag": "E1", "label": "특허법 제30조", ...}] (answer_question 결과의 evidence)."""
    labels = {e["tag"]: e["label"] for e in evidence}

    def label_of(m: re.Match) -> str | None:
        return labels.get(f"E{int(m.group(1))}")

    def fix_group(m: re.Match) -> str:
        open_, body, close = m.groups()
        if not _TAG.search(body):
            return m.group(0)
        if _ARTICLE.search(_TAG.sub("", body)):  # 이미 조문을 말하고 있으면 꼬리표만 지운다
            new = _TAG.sub("", body)
        else:
            used: list[str] = []

            def replace(mm: re.Match) -> str:
                lab = label_of(mm)
                if lab is None or lab in used:  # 근거에 없는 꼬리표, 같은 이름의 중복은 생략
                    return ""
                used.append(lab)
                return lab

            new = _TAG.sub(replace, body)
        new = re.sub(r"(\s*,\s*)+", ", ", new).strip(" ,")
        return f"{open_}{new}{close}" if new else ""

    out = _GROUP.sub(fix_group, answer)
    out = _TAG.sub(lambda m: label_of(m) or "", out)  # 괄호 밖 꼬리표
    return re.sub(r"\s+([.,。!?])", r"\1", out)  # 지운 자리에 남은 공백 정리
