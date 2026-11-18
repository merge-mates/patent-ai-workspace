"""검색 계약 오류 (design.md 7-1절)."""


class RetrievalError(Exception):
    """검색 계약 오류의 뿌리."""


class UnknownImplError(RetrievalError):
    """등록되지 않은 impl 이름. 메시지에 쓸 수 있는 이름 목록을 담는다."""


class ModeNotSupportedError(RetrievalError):
    """지원하지 않는 검색 방식 (지금은 hybrid)."""


class UnknownIndexVersionError(RetrievalError):
    """저장소에 없는 색인 판."""


class SearchContractViolationError(RetrievalError):
    """구현이 돌려준 결과가 계약을 어김 (개수 > k, 순서 틀림)."""


class IndexVersionMismatchError(SearchContractViolationError):
    """결과에 설정과 다른 색인 판 조각이 섞임."""


class RecordedEmbeddingMissing(RetrievalError):
    """fake 구현: 녹화해 둔 질의 벡터에 이 질의가 없다 (실제 모델을 부르지 않는다)."""
