"""인용문헌 색인 (쪽 글자 추출 → 머리말·꼬리말 빼기 → 청킹 → cite_chunks).

여기 `PageText`는 쪽 하나의 줄 목록이다. core F1의 `PageText`(문서 한 건)와 다른 타입이고,
retrieval은 core를 import하지 않아서 따로 둔다 (design 2절 1단계)."""

from patent_ai.retrieval.cite_index.header_footer import (
    HeaderFooterConfig,
    load_header_footer_config,
    strip_repeated,
)
from patent_ai.retrieval.cite_index.pages import (
    PageExtractor,
    PageText,
    PdfplumberExtractor,
)

__all__ = [
    "HeaderFooterConfig",
    "PageExtractor",
    "PageText",
    "PdfplumberExtractor",
    "load_header_footer_config",
    "strip_repeated",
]
