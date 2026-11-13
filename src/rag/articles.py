"""조문 원문 조회: 화면에서 인용 조문을 눌렀을 때 보여 줄 원문과 출처.

원문은 별도 텍스트 파일이 아니라 청커가 법제처 JSON 에서 만든 조문 단위 청크 파일에서 읽는다
(data/processed/chunks_법령3_article.jsonl, 조문 한 개 = 한 줄, 메타데이터 포함). 이 파일은 git 에 올리지 않는 로컬 데이터다.
"""
import json
from pathlib import Path

from src.law_api.chunker import strip_amend_tags


def load_articles(path: Path) -> dict[str, dict]:
    """조문 id("특허법#제30조") -> 청크 한 줄(chunk_id, text, metadata)."""
    rows = (json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip())
    return {r["chunk_id"]: r for r in rows}


def _date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}" if len(yyyymmdd) == 8 else yyyymmdd


def get_article(articles: dict[str, dict], article_id: str, hide_amendments: bool = True) -> dict | None:
    """화면에 보여 줄 조문 원문. 없으면 None. hide_amendments 이면 본문의 <개정 …> 표기를 숨긴다."""
    row = articles.get(article_id)
    if row is None:
        return None
    md = row["metadata"]
    text = strip_amend_tags(row["text"]) if hide_amendments else row["text"]
    return {
        "article_id": article_id,
        "law_name": md["law_name"],
        "label": f"{md['law_name']} {md['label']}",
        "title": md.get("title"),
        "chapter": md.get("chapter"),
        "text": text,
        "source": f"{md['law_name']} (시행 {_date(md['law_effective_date'])}, 판본 {md['law_mst']})",
    }
