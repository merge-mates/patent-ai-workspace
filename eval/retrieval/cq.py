"""CQ 후보 파일 쓰기 (design.md 7-1 CQ 후보 파일).

CQ 후보 = 검색 결과 안(가장 큰 k)에서 정답 항목을 하나도 못 찾은 줄.
파일에는 질의·정답 위치가 들어가므로 git 밖 폴더에만 쓴다 (폴더 검사는 preflight가 한다).
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write_cq(report, path: str | Path) -> int:
    """못 맞힌 줄을 한 줄씩 jsonl로 쓰고 줄 수를 돌려준다. why는 사람이 나중에 채운다."""
    s = report.scores
    lines = []
    for r in report.rows:
        # 순위마다 맞힌 항목 집합이 모두 비면 가장 큰 k 안에 맞은 게 없는 것
        if any(r.found_by_rank):
            continue
        lines.append(
            {
                "row_id": r.row.row_id,
                "goldset_version": s["goldset_version"],
                "gold_sha256": s["gold_sha256"],
                "corpus": s["corpus"],
                "impl": s["impl"],
                "mode": s["mode"],
                "index_version": s["index_version"],
                "k": report.k_max,
                "query": r.row.query,
                "items": [i.model_dump(mode="json") for i in r.row.items],
                "found": [
                    {"chunk_id": h.chunk_id, "label": h.location.label, "score": h.score}
                    for h in r.hits
                ],
                "why": "",
            }
        )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    if not lines:
        # 로그에는 건수만 (질의 글자 없음)
        logger.warning("CQ 후보가 0건이다 (점수에 넣은 줄 %d개)", len(report.rows))
    return len(lines)
