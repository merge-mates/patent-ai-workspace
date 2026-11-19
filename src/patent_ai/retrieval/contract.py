"""검색 인터페이스·등록표·공통 검사 래퍼 (design.md 7-1절).

core를 import하지 않는다 (부르는 방향이 core -> retrieval).
"""

import importlib
import re
from collections.abc import Callable
from datetime import date
from typing import Protocol, get_args

from patent_ai.retrieval.errors import (
    IndexVersionMismatchError,
    ModeNotSupportedError,
    SearchContractViolationError,
    UnknownImplError,
    UnknownIndexVersionError,
)
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Corpus, Mode, SearchResult


class Searcher(Protocol):
    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult: ...


class _IndexVersionLookup(Protocol):
    """래퍼가 저장소에서 필요한 것은 이 하나뿐이다 (전체 저장소 Protocol은 repository.py)."""

    def has_index_version(self, corpus: Corpus, index_version: str) -> bool: ...


# 글 -> 벡터 함수. 부르는 쪽(채점기, F2·F3)이 core/llm의 embed를 넘긴다.
# retrieval은 core를 import하지 않으므로 모델 호출을 직접 하지 않고 이 함수만 받는다
Embed = Callable[[str], list[float]]

# impl 이름 -> 구현 클래스. 구현은 register_impl로 이름만 더하면 된다
_REGISTRY: dict[str, Callable[..., Searcher]] = {}


def register_impl(name: str) -> Callable[[Callable[..., Searcher]], Callable[..., Searcher]]:
    """구현 클래스를 이름으로 등록하는 데코레이터. 클래스는 (repo, settings, embed)로 만들어진다."""

    def deco(cls: Callable[..., Searcher]) -> Callable[..., Searcher]:
        # 같은 이름에 다른 클래스가 덮어쓰면 어느 구현이 도는지 알 수 없다. 막는다
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            raise ValueError(f"impl {name!r}은 이미 등록돼 있다")
        _REGISTRY[name] = cls
        return cls

    return deco


class CheckedSearcher:
    """어느 구현이든 같은 검사를 하는 래퍼. 구현은 검사를 다시 하지 않아도 된다."""

    def __init__(self, inner: Searcher, repo: _IndexVersionLookup, index_version: str) -> None:
        self._inner = inner
        self._repo = repo
        self._index_version = index_version

    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult:
        # --- 부르기 전 검사 ---
        if corpus not in get_args(Corpus):
            raise ValueError(f"corpus 값이 올바르지 않다: {corpus!r}")
        if mode not in get_args(Mode):
            raise ValueError(f"mode 값이 올바르지 않다: {mode!r}")
        if k < 1:
            raise ValueError(f"k는 1 이상이어야 한다: {k}")
        # None만 "전체"다. 빈 목록은 실수로 보고 막는다
        if doc_ids is not None and len(doc_ids) == 0:
            raise ValueError("doc_ids가 빈 목록이다 (전체는 None)")
        if mode == "hybrid":
            raise ModeNotSupportedError("hybrid는 아직 지원하지 않는다 (bm25, vector만)")
        if not self._repo.has_index_version(corpus, self._index_version):
            raise UnknownIndexVersionError(f"{corpus} 표에 색인 판 {self._index_version!r}이 없다")

        result = self._inner.search(query, corpus, mode, k, doc_ids=doc_ids, as_of=as_of)

        # --- 받은 뒤 검사 ---
        # 부른 말뭉치·방식·k와 다른 결과면 구현이 엉뚱한 것을 돌려준 것이다
        if result.corpus != corpus or result.mode != mode or result.scope.k != k:
            raise SearchContractViolationError(
                f"결과 머리가 요청과 다르다: corpus {result.corpus!r}/{corpus!r}, "
                f"mode {result.mode!r}/{mode!r}, k {result.scope.k}/{k}"
            )
        if len(result.hits) > k:
            raise SearchContractViolationError(f"결과 {len(result.hits)}개가 k={k}보다 많다")
        mixed = [h for h in result.hits if h.index_version != self._index_version]
        if result.index_version != self._index_version or mixed:
            raise IndexVersionMismatchError(
                f"설정 색인 판 {self._index_version!r}과 다른 결과가 섞였다 (조각 {len(mixed)}개)"
            )
        # 점수 내림차순, 같은 점수는 chunk_id 오름차순
        keys = [(-h.score, h.chunk_id) for h in result.hits]
        if keys != sorted(keys):
            raise SearchContractViolationError(
                "결과 순서가 점수 내림차순·chunk_id 오름차순이 아니다"
            )
        return result


_IMPL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _import_impl(impl: str) -> None:
    """impl 이름으로 구현 모듈 patent_ai.retrieval.<impl>을 import한다 (design 7-1).

    그 모듈이 @register_impl("<impl>")로 자기를 등록한다. 모듈이 없으면 아무것도 안 하고
    get_searcher가 UnknownImplError를 낸다. 모듈 안의 다른 import 오류는 그대로 올린다.
    """
    if not _IMPL_NAME.match(impl):
        return  # 점·슬래시가 든 이름으로 엉뚱한 모듈을 부르지 않게
    name = f"patent_ai.retrieval.{impl}"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name != name:
            raise
        return
    if impl not in _REGISTRY:
        # 이미 import된 모듈이면 등록 코드가 다시 돌지 않으므로 한 번 다시 읽는다
        importlib.reload(module)


def get_searcher(
    impl: str, repo: ChunkRepository, settings: dict, embed: Embed | None = None
) -> Searcher:
    """이름으로 구현을 골라 CheckedSearcher로 감싸 돌려준다.

    embed: 질의 글을 벡터로 바꾸는 함수. vector 검색 구현이 쓴다 (bm25만 쓰면 None).
    """
    if impl not in _REGISTRY:
        _import_impl(impl)
    if impl not in _REGISTRY:
        raise UnknownImplError(
            f"없는 impl {impl!r}. impl 이름은 retrieval/<이름>.py와 같아야 함"
            f"(소문자·숫자·밑줄). 쓸 수 있는 이름: {sorted(_REGISTRY)}"
        )
    if not settings.get("index_version"):
        raise ValueError("settings에 index_version이 없다")
    inner = _REGISTRY[impl](repo, settings, embed)
    return CheckedSearcher(inner, repo, settings["index_version"])
