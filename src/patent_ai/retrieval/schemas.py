"""검색 계약의 데이터 모양 (design.md 3-2절, 5-1절).

core를 import하지 않는다 (부르는 방향이 core -> retrieval).
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 어느 말뭉치(표)인지, 어떤 검색 방식인지
Corpus = Literal["law", "cite"]
Mode = Literal["bm25", "vector", "hybrid"]

ChunkKind = Literal[
    "body",
    "claim",
    "abstract",
    "figure_desc",
    "article",
    "guideline",
    "judgment",
    "judgment_summary",
]
# 법령 말뭉치 조각의 자료 유형 / 판례·심결에서 그 글을 쓴 쪽 (인용문헌 조각은 둘 다 비운다)
SourceKind = Literal["statute", "guideline", "precedent", "trial"]
Speaker = Literal["court", "party", "unknown"]
LocKind = Literal["paragraph", "column_line", "article", "page", "figure", "claim", "abstract"]
# 법령 판본 상태. 인용문헌은 not_applicable, 판본을 모르면 unverified(빈칸 안 됨)
EditionStatus = Literal["confirmed", "unverified", "not_applicable"]
# 검색 결과가 비었을 때만 쓰는 상태. confirmed/conflict는 검색이 붙이지 않는다
SearchStatus = Literal["not_found_in_scope", "unverified"]
StatusReason = Literal["body_missing"]  # #103 core/schemas/common.py와 같은 이름


class _Strict(BaseModel):
    # 모르는 칸이 들어오면 오류로 막는다 (조용히 버리지 않음)
    model_config = ConfigDict(extra="forbid")


class Location(_Strict):
    """조각이 원문 어디에 있나."""

    kind: LocKind
    start: int | None = None
    end: int | None = None
    label: str  # 원문 표기 그대로 ([0023], 3:10-25 ...)
    figures: list[int] = Field(default_factory=list)
    claims: list[int] = Field(default_factory=list)


class Edition(_Strict):
    """법령 판본(시행 기간). 인용문헌은 status만 not_applicable."""

    status: EditionStatus
    effective_from: date | None = None
    effective_to: date | None = None  # 없으면 현행
    label: str | None = None


class Chunk(_Strict):
    """색인 조각 하나. 저장소가 돌려주고 Matcher가 받는다."""

    chunk_id: str
    index_version: str
    doc_id: str
    chunk_kind: ChunkKind
    location: Location
    edition: Edition
    text: str
    # 벡터 검색용. 검색 결과 JSON에는 싣지 않는다 (SearchHit에서 제외)
    embedding: list[float] | None = None
    # 아래 넷은 법령 표(law)에만 쓴다 (design 5-1). 인용문헌 조각은 비운다.
    source_kind: SourceKind | None = None
    decided_on: date | None = None  # 판례·심결의 선고(결정)일
    speaker: Speaker | None = None  # 판례·심결에서 판단(법원)인지 당사자 주장인지
    attrs: dict[str, Any] | None = None  # 법원·사건명 같은 보이기용 칸 (거르기에는 안 씀)


class SearchHit(Chunk):
    """검색에 걸린 조각 + 점수 + 순위(1부터). 근거 '후보'일 뿐 확인됨이 아니다."""

    embedding: list[float] | None = Field(default=None, exclude=True)
    score: float
    rank: int = Field(ge=1)


class SearchScope(_Strict):
    """찾아본 범위."""

    doc_ids: list[str] | None = None  # None = 전체
    as_of: date | None = None
    k: int
    # 점수 매기기 전에 건 거르기 (None = 안 걺). design 3-2절
    chunk_kinds: list[ChunkKind] | None = None
    source_kinds: list[SourceKind] | None = None
    decided_on_or_before: date | None = None  # 판례·심결은 선고일이 이 날 이하(그날 포함)만


class SearchResult(_Strict):
    corpus: Corpus
    index_version: str
    mode: Mode
    scope: SearchScope
    status: SearchStatus | None = None
    status_reason: StatusReason | None = None
    skipped_unverified_edition: int = Field(default=0, ge=0)
    # decided_on_or_before를 걸었을 때 선고일을 몰라 빠진 판례·심결 조각 수 (안 걸면 0)
    skipped_unknown_date: int = Field(default=0, ge=0)
    hits: list[SearchHit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _상태는_빈_결과일_때만(self) -> SearchResult:
        # 결과가 있으면 status는 null, 비었을 때만 값을 가진다
        if self.hits:
            if self.status is not None:
                raise ValueError("hits가 있으면 status는 null이어야 한다")
        elif self.status is None:
            raise ValueError("hits가 비면 status가 있어야 한다")
        # 이유(status_reason)는 unverified일 때만, 그리고 꼭 있어야 한다
        if self.status == "unverified" and self.status_reason is None:
            raise ValueError("status가 unverified이면 status_reason이 있어야 한다")
        if self.status != "unverified" and self.status_reason is not None:
            raise ValueError("status_reason은 status가 unverified일 때만 쓴다")
        return self
