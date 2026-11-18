from patent_ai.retrieval import fake  # noqa: F401  (fake 등록. 계약의 일부)
from patent_ai.retrieval.contract import CheckedSearcher, Searcher, get_searcher, register_impl
from patent_ai.retrieval.errors import (
    IndexVersionMismatchError,
    ModeNotSupportedError,
    RecordedEmbeddingMissing,
    RetrievalError,
    SearchContractViolationError,
    UnknownImplError,
    UnknownIndexVersionError,
)

__all__ = [
    "CheckedSearcher",
    "IndexVersionMismatchError",
    "ModeNotSupportedError",
    "RecordedEmbeddingMissing",
    "RetrievalError",
    "SearchContractViolationError",
    "Searcher",
    "UnknownImplError",
    "UnknownIndexVersionError",
    "get_searcher",
    "register_impl",
]
