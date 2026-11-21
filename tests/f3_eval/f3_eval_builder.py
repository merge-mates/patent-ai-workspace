"""F3 채점 테스트용 가짜 정답·예측·조각 만들기 (손으로 지은 번호, 원문 없음)."""

import json
from pathlib import Path

from patent_ai.retrieval.schemas import Chunk, Edition, Location

FIX_F1 = Path(__file__).resolve().parents[1] / "fixtures" / "f1_eval"
APP, DISPATCH = "1020990000001", "952099000000001"
KEY = f"{APP}_{DISPATCH}"
DOC = "KR20990000001A"
IV = "cite-idx-v2"
UNIT = f"{DISPATCH}:29-2:c1"
CLARITY_UNIT = f"{DISPATCH}:42-4-2:c2"
TERM = "상기 프리뷰 이미지"  # 가짜 F1 정답(gold_ok.json)의 청구항 2 명확성 표현
CLAIM_2 = "제1항에 있어서, 상기 프리뷰 이미지를 보이는 장치."


def chunk_id(no: int) -> str:
    return f"{IV}:{DOC}:p{no:04d}"


def chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id=chunk_id(no),
            index_version=IV,
            doc_id=DOC,
            chunk_kind="body",
            location=Location(kind="paragraph", start=no, end=no, label=f"[{no:04d}]"),
            edition=Edition(status="not_applicable"),
            text=f"문단 {no}",
        )
        for no in (14, 20, 80, 81)
    ]


def cite_gold_lines() -> list[dict]:
    """청구항 1: [0014]와 [0080]-[0081] / 청구항 2: 위치 없음(빼는 줄)."""
    para = {"kind": "paragraph", "start": 14, "end": 14, "label": "[0014]"}
    span = {"kind": "paragraph", "start": 80, "end": 81, "label": "[0080]-[0081]"}
    base = {"corpus": "cite", "query": "질의 글자", "doc_ids": [DOC]}
    return [
        {**base, "row_id": f"{DISPATCH}:r1:c1:{DOC}", "items": [para, span]},
        {**base, "row_id": f"{DISPATCH}:r1:c2:{DOC}", "items": [], "exclude": "no_location"},
    ]


def prediction(
    *,
    searched=((1, [14, 20]), (2, [20])),
    selected=(20,),
    source="ai_found",
    clarity_location="청구항 2 [글자 10-19]",
    novelty_tables=(),
    element_claims=None,
) -> dict:
    """F3Result를 dump한 모양의 예측. searched: (구성요소 번호, 걸린 문단 번호들).

    element_claims: {구성요소 번호: 그 구성요소가 있는 청구항} (없으면 옛 예측처럼 칸을 뺀다).
    """
    claim_of = element_claims or {}
    ok = {"value": "confirmed", "reason": None, "checked": "테스트", "searched_scope": None}
    rows = [
        {
            "claim": 1,
            "citation": "D1",
            "paragraph_source": source,
            "judgment": "disclosed",
            "evidence": [{"document_id": DOC, "chunk_id": chunk_id(no), "index_version": IV}],
            "status": ok,
        }
        for no in selected
    ]
    table = {
        "unit_id": UNIT,
        "rejection_kind": "inventive_step",
        "citations": [{"label": "D1", "number": DOC, "compared": True}],
        "rows": rows,
        "status": ok,
    }
    return {
        "oa_id": DISPATCH,
        "units": [
            {"unit_id": UNIT, "rejection": 1, "rejection_kind": "inventive_step"},
            {"unit_id": CLARITY_UNIT, "rejection": 2, "rejection_kind": "clarity"},
        ],
        "comparisons": [table, *novelty_tables],
        "clarity_reviews": [
            {
                "unit_id": CLARITY_UNIT,
                "claim": 2,
                "term": TERM,
                "claim_location": clarity_location,
                "status": ok,
            }
        ],
        "search_log": [
            {
                "unit_id": UNIT,
                "claim": 1,
                "element_no": no,
                **({"element_claim": claim_of[no]} if no in claim_of else {}),
                "citation": "D1",
                "doc_id": DOC,
                "round": 1,
                "hit_chunk_ids": [chunk_id(n) for n in hits],
            }
            for no, hits in searched
        ],
        "examiner_locations": [],
        "status": ok,
    }


def novelty_table(compared: list[bool], row_labels: list[str]) -> dict:
    labels = [f"D{i}" for i in range(1, len(compared) + 1)]
    return {
        "unit_id": f"{DISPATCH}:29-1-1:c1",
        "rejection_kind": "novelty",
        "citations": [
            {"label": label, "number": DOC, "compared": c}
            for label, c in zip(labels, compared, strict=True)
        ],
        "rows": [
            {"claim": 1, "citation": label, "paragraph_source": "ai_found", "evidence": []}
            for label in row_labels
        ],
    }


def write_goldset(root: Path, *, cite=True, f1=True, version=1) -> None:
    """tmp에 가짜 정답 세트를 쓴다 (retrieval/cite_gold.jsonl, f1/<키>.json)."""
    (root / "tune").mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(f"{version}\n")
    if cite:
        (root / "tune" / "retrieval").mkdir()
        text = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cite_gold_lines())
        (root / "tune" / "retrieval" / "cite_gold.jsonl").write_text(text, encoding="utf-8")
    if f1:
        (root / "tune" / "f1").mkdir()
        gold = (FIX_F1 / "gold_ok.json").read_text(encoding="utf-8")
        (root / "tune" / "f1" / f"{KEY}.json").write_text(gold, encoding="utf-8")


def write_run(folder: Path, pred: dict, *, inputs=True, key: str = KEY) -> None:
    """예측 폴더: <키>.f3.json 과 (청구항 글자가 든) <키>.inputs.json."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.f3.json").write_text(json.dumps(pred, ensure_ascii=False), encoding="utf-8")
    if inputs:
        body = {"claims_at_oa": {"1": "화분.", "2": CLAIM_2}}
        (folder / f"{key}.inputs.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )


def write_chunks(path: Path) -> Path:
    path.write_text("".join(c.model_dump_json() + "\n" for c in chunks()), encoding="utf-8")
    return path
