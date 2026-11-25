"""의견서 글자 읽기 도구: 청구항 번호 언급, 문장 나누기, 묶음 처리 문장 (모델 없이)."""

import re

# 청구항 번호 목록 꼴: "1, 11-13, 20", "제1항 내지 제4항"
_LIST = r"\d+(?:\s*항?\s*(?:,|-|~|내지|및|와|과|또는|ㆍ|·)\s*(?:제\s*)?(?:청구항\s*)?\d+)*"
_MENTION = [
    re.compile(rf"(?:청구항\s*)?제\s*({_LIST})\s*항"),
    re.compile(rf"청구항\s*(?:제\s*)?({_LIST})(?!\s*\d)"),
    re.compile(rf"(?<![\d.\-])({_LIST})\s*항(?![목])"),
]


def expand(spec: str) -> list[int]:
    """'1, 3-5 내지 7' 같은 글자를 번호 목록으로 (범위가 200개를 넘거나 거꾸로면 버림)."""
    spec = re.sub(r"(항|제|청구|\s)", " ", spec)
    spec = spec.replace("내지", "-").replace("~", "-").replace("또는", ",").replace("및", ",")
    spec = re.sub(r"\s*-\s*", "-", spec)  # "1 - 4" -> "1-4" (범위를 한 조각으로)
    out: list[int] = []
    for part in re.split(r"[,\s]+(?![-])", spec.strip()):
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part.strip())
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo <= hi < lo + 200:
                out.extend(range(lo, hi + 1))
        else:
            out.extend(int(x) for x in re.findall(r"\d+", part))
    return out


def mentioned_claims(text: str, max_claim: int = 200) -> set[int]:
    """글에 나온 청구항 번호 전부."""
    out: set[int] = set()
    for rx in _MENTION:
        for m in rx.finditer(text):
            out |= {n for n in expand(m.group(1)) if 1 <= n <= max_claim}
    return out


def squash(s: str) -> str:
    """띄어쓰기를 모두 뺀 글. PDF 줄바꿈이 낱말을 끊어('인 용하는') 낱말 찾기는 이것으로 한다."""
    return re.sub(r"\s+", "", s)


def clauses(text: str) -> list[str]:
    """문장을 '…하고,'·쉼표 앞뒤로 더 나눈 마디.

    한 문장에 삭제와 부가가 같이 있을 때 항마다 가르려고 쓴다.
    """
    out = []
    for s in sentences(text):
        out += [
            c.strip()
            for c in re.split(r"(?<=고)\s*,\s*|(?<=며)\s*,?\s+|,\s*(?=(?:청구항\s*)?제?\s*\d)", s)
            if c.strip()
        ]
    return out


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s*\n\s*", " ", text)
    parts = re.split(r"(?<=[다요음])\.\s+|(?<=습니다)\.?\s+", flat)
    return [s.strip() for s in parts if s.strip()]


# 묶음 처리 문장: "종속항 역시/또한…", "제N항을 인용하는 청구항 제M항도…"
_BUNDLE = re.compile(
    r"(종속항|나머지청구항|청구항제?\d+[^.]{0,40}(?:을|를)인용)[^.]{0,200}?"
    r"(역시|또한|마찬가지|동일한이유|같은이유|함께|당연히|인용하(?:고|므로|는)|한정하|(?:항|들)도)"
)


def bundle_sentences(text: str) -> list[str]:
    return [s for s in sentences(text) if _BUNDLE.search(squash(s))]


def bundle_covers(text: str, claim: int) -> bool:
    """묶음 문장이 그 항을 덮나: 문장에 그 항 번호가 있거나, 번호 없이 '종속항'이라고만 쓴 문장."""
    for s in bundle_sentences(text):
        nums = mentioned_claims(s)
        if claim in nums:
            return True
        if "종속항" in squash(s) and not (nums - _independent_like(s)):
            return True
    return False


def _independent_like(s: str) -> set[int]:
    """'독립항 1, 11항', '청구항 1을 인용하는'처럼 기준 항으로 쓴 번호 (덮는 대상이 아님)."""
    out: set[int] = set()
    for m in re.finditer(
        rf"(?:독립\s*(?:청구)?항\s*(?:제\s*)?|청구항\s*(?:제\s*)?)({_LIST})\s*항?\s*(?:[이가은는을를]|의|에)?\s*(?:인\s*용|과\s*동일|와\s*동일|이\s*진보)",
        s,
    ):
        out |= set(expand(m.group(1)))
    for m in re.finditer(rf"독립\s*(?:청구)?항\s*(?:제\s*)?({_LIST})", s):
        out |= set(expand(m.group(1)))
    return out
