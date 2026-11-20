"""F3 예측(F3Result를 dump한 JSON)에서 채점에 쓰는 칸만 읽는 모양.

앱의 결과 모델로 검사하지 않는다: 규칙을 어긴 예측(신규성 표가 두 문헌을 합침 등)도
읽어서 위반으로 세야 하기 때문이다. 모르는 칸은 넘긴다.
"""

from pydantic import BaseModel, ConfigDict, Field


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PredEvidence(_Loose):
    document_id: str
    chunk_id: str | None = None
    index_version: str | None = None


class PredRow(_Loose):
    claim: int
    citation: str
    paragraph_source: str
    evidence: list[PredEvidence] = Field(default_factory=list)


class PredCitation(_Loose):
    label: str
    compared: bool


class PredTable(_Loose):
    unit_id: str
    rejection_kind: str
    citations: list[PredCitation] = Field(default_factory=list)
    rows: list[PredRow] = Field(default_factory=list)


class PredUnit(_Loose):
    unit_id: str
    rejection: int
    rejection_kind: str


class PredSearch(_Loose):
    unit_id: str
    claim: int
    element_no: int
    doc_id: str
    round: int = 1
    hit_chunk_ids: list[str] = Field(default_factory=list)


class PredClarity(_Loose):
    unit_id: str
    claim: int
    term: str
    claim_location: str


class F3Pred(_Loose):
    oa_id: str
    units: list[PredUnit] = Field(default_factory=list)
    comparisons: list[PredTable] = Field(default_factory=list)
    clarity_reviews: list[PredClarity] = Field(default_factory=list)
    search_log: list[PredSearch] = Field(default_factory=list)
    examiner_locations: list[dict] = Field(default_factory=list)
