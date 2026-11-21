"""BM25 낱말 자르기 (cite-search design 7-2절, #66 법령).

- kiwi: Kiwi 형태소 분석. 조사·어미는 버리고 체언·용언 어간·외국어·숫자만 남겨
  BM25가 "필러를"과 "필러"를 같은 낱말로 본다.
- char_bigram: 공백 낱말을 두 글자씩 겹쳐 자른다. 의존성 없음.
- whitespace: 공백으로만 자른다.
`make_tokenizer(이름, pos_tags)`로 고른다 (실험 설정 settings.tokenizer).
core를 import하지 않는다. 모델 호출 없음 (Kiwi는 로컬 형태소 분석기).
"""

from typing import Protocol

from kiwipiepy import Kiwi

TOKENIZERS: tuple[str, ...] = ("kiwi", "char_bigram", "whitespace")

# 기본 남길 품사. 실험 설정(settings.pos_tags)이 이 값을 덮어쓴다
# NNG 일반명사, NNP 고유명사, NNB 의존명사, NR 수사, VV 동사, VA 형용사(어간), XR 어근,
# SL 외국어, SN 숫자, SH 한자. (대명사 NP·조사·어미·접사는 검색에 도움이 안 돼 뺀다)
DEFAULT_POS_TAGS: tuple[str, ...] = (
    "NNG",
    "NNP",
    "NNB",
    "NR",
    "VV",
    "VA",
    "XR",
    "SL",
    "SN",
    "SH",
)


class KiwiTokenizer:
    def __init__(self, pos_tags: list[str] | tuple[str, ...] | None = None) -> None:
        self._tags = frozenset(pos_tags if pos_tags is not None else DEFAULT_POS_TAGS)
        # Kiwi는 만드는 데 오래 걸려 처음 쓸 때 한 번만 만든다 (tokenizer 하나에 Kiwi 하나)
        self._kiwi: Kiwi | None = None

    def tokenize(self, text: str) -> list[str]:
        if self._kiwi is None:
            self._kiwi = Kiwi()
        out: list[str] = []
        for tok in self._kiwi.tokenize(text):
            if tok.tag not in self._tags:
                continue
            # 영어는 대소문자를 합쳐 "Silicon"과 "silicon"이 같은 낱말이 되게 한다
            out.append(tok.form.lower() if tok.tag == "SL" else tok.form)
        return out


class Tokenizer(Protocol):
    def tokenize(self, text: str) -> list[str]: ...


class CharBigramTokenizer:
    """'발명은' → ['발명', '명은']. 한 글자 낱말은 그대로.

    조사가 붙어도('발명은'/'발명을') 앞 두 글자가 같이 걸리게.
    """

    def tokenize(self, text: str) -> list[str]:
        return [w[i : i + 2] for w in text.split() for i in range(max(len(w) - 1, 1))]


class WhitespaceTokenizer:
    def tokenize(self, text: str) -> list[str]:
        return text.split()


def make_tokenizer(name: str, pos_tags: list[str] | None = None) -> Tokenizer:
    """설정 이름 → 토크나이저. pos_tags는 kiwi에만 뜻이 있어 다른 것과 같이 오면 막는다."""
    if name not in TOKENIZERS:
        raise ValueError(f"모르는 tokenizer {name!r}. 쓸 수 있는 것: {TOKENIZERS}")
    if name == "kiwi":
        return KiwiTokenizer(pos_tags)
    # 조용히 무시하지 않는다: 설정에 적힌 값이 점수에 안 쓰이면 실험 기록이 틀려진다
    if pos_tags is not None:
        raise ValueError(f"pos_tags는 kiwi에만 쓴다 (tokenizer={name!r})")
    return CharBigramTokenizer() if name == "char_bigram" else WhitespaceTokenizer()
