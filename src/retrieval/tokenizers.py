"""한국어 토크나이저 (M2 후보).

- kiwi_tokenizer: 형태소 분석(kiwipiepy) 후 내용어(명사·용언 어간·어근·외래어·숫자)만 남김.
  조사·어미·부호는 버린다. 예: "공공질서에" -> 공공, 질서.
- char_ngram_tokenizer(n): 공백으로 나눈 낱말마다 글자 n-gram. 사전·형태소 분석이 필요 없다.
  낱말이 n글자보다 짧으면 그 낱말 자체를 토큰으로 쓴다.
"""
import re
from functools import lru_cache

_KEEP_TAGS = {"NNG", "NNP", "VV", "VA", "XR", "SL", "SN"}
_PUNCT_RE = re.compile(r"[^\w]+", re.UNICODE)


@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi  # 설치돼 있을 때만 불러온다
    return Kiwi()


def kiwi_tokenizer(text: str) -> list[str]:
    return [t.form for t in _kiwi().tokenize(text) if t.tag.split("-")[0] in _KEEP_TAGS]


def char_ngram_tokenizer(n: int = 2):
    def tokenize(text: str) -> list[str]:
        out: list[str] = []
        for word in text.split():
            word = _PUNCT_RE.sub("", word)
            if not word:
                continue
            if len(word) <= n:
                out.append(word)
            else:
                out.extend(word[i:i + n] for i in range(len(word) - n + 1))
        return out
    return tokenize
