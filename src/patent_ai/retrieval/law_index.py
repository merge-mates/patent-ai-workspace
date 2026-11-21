"""법령 청커: 법제처 본문 JSON → 법령 색인 조각 JSONL (#66).

정한 것 (이슈 #66 본문 구현 계획):
- 항 단위로 자른다. 호·목은 그 항 조각 안에 둔다. 조각 글 앞에 조 제목을 붙인다.
- 항이 없거나 항번호 없이 호만 있는 조는 조 하나가 조각 하나(항 0).
- 위치 번호 = 조×10000 + 가지×100 + 항 (29조 2항 = 290002).
- 판본: 파일의 시행일이 시작일, 같은 법 다음 판 시행일 하루 전이 끝일. 마지막 판은 끝일 없음.
  시행일을 못 읽으면 unverified.
- doc_id = 원본 파일 이름에서 body_ 와 .json 을 뗀 것 (특허법_212229_20200311).

실행: uv run python -m patent_ai.retrieval.law_index --config config/index/law-idx-v1.yaml
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from patent_ai.index_version import is_index_version
from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.schemas import Chunk, Edition, Location

logger = logging.getLogger(__name__)

_RAW_NAME = re.compile(r"^body_(?P<doc_id>(?P<law>.+)_(?P<mst>[0-9]+)_(?P<date>[0-9]{8}))\.json$")
# 개정 꼬리표: <개정 2016.2.29>, <신설 …>, <2006.3.3> 처럼 날짜가 든 꺾쇠 묶음
_AMEND_TAG = re.compile(r"<[^<>]*[0-9]{4}\.\s?[0-9]{1,2}\.\s?[0-9]{1,2}\.?[^<>]*>")
# 조 머리: 제29조, 제7조의2, 뒤에 (제목)이 있으면 같이
_ARTICLE_HEAD = re.compile(r"^제[0-9]+조(?:의[0-9]+)?(?:\([^)]*\))?")
_DELETED_ARTICLE = re.compile(r"^제[0-9]+조(?:의[0-9]+)?(?:\([^)]*\))?\s*삭제$")
_CIRCLED_ONE = ord("①")


class LawIndexError(RetrievalError):
    """법령 색인을 만들 수 없다 (원본 모양이 틀림, 조각 0개, 덮어쓰기 등)."""


def article_loc(jo: int, gaji: int, hang: int) -> int:
    """조·가지·항을 정렬·비교용 숫자 하나로 (6자리)."""
    return jo * 10000 + gaji * 100 + hang


def parse_raw_name(filename: str) -> tuple[str, str]:
    """원본 파일 이름 → (법령 이름 키, doc_id). 예: body_특허법_시행령_233263_20210623.json"""
    m = _RAW_NAME.match(filename)
    if not m:
        raise LawIndexError(f"법령 원본 파일 이름 모양이 아니다: {filename}")
    return m["law"], m["doc_id"]


def _clean(text: str) -> str:
    # 개정 꼬리표를 지우고 공백을 하나로
    return re.sub(r"\s+", " ", _AMEND_TAG.sub("", text)).strip()


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _flatten(x) -> list[str]:
    # 목내용은 글 하나이거나 [["어. …", "1) …"]] 같은 겹목록이다
    if isinstance(x, list):
        return [s for item in x for s in _flatten(item)]
    return [x] if isinstance(x, str) else []


def _is_deleted(text: str) -> bool:
    # "③ 삭제", "4. 삭제" 처럼 번호 뒤 글이 '삭제'뿐이면 지워진 항·호
    return re.sub(r"^\S+\s*", "", text, count=1) == "삭제"


def _ho_texts(items) -> list[str]:
    """호와 그 아래 목 글을 순서대로. 지워진 호는 뺀다."""
    out: list[str] = []
    for ho in _as_list(items):
        t = _clean(ho.get("호내용", ""))
        if not t or _is_deleted(t):
            continue
        out.append(t)
        for mok in _as_list(ho.get("목")):
            mt = _clean(" ".join(_flatten(mok.get("목내용", ""))))
            if mt and not _is_deleted(mt):
                out.append(mt)
    return out


def _hang_no(mark: str) -> int:
    n = ord(mark.strip()[:1]) - _CIRCLED_ONE + 1 if mark.strip() else 0
    if not 1 <= n <= 20:
        raise LawIndexError(f"항번호를 읽을 수 없다: {mark!r}")
    return n


def _label(jo: int, gaji: int, hang: int) -> str:
    s = f"제{jo}조" + (f"의{gaji}" if gaji else "")
    return s + (f"제{hang}항" if hang else "")


def chunk_law(data: dict, doc_id: str, edition: Edition, index_version: str) -> list[Chunk]:
    """법령 JSON 하나 → 항 단위 조각 목록."""
    chunks: list[Chunk] = []

    def add(jo: int, gaji: int, hang: int, text: str) -> None:
        loc = article_loc(jo, gaji, hang)
        chunks.append(
            Chunk(
                chunk_id=f"{index_version}:{doc_id}:{loc}",
                index_version=index_version,
                doc_id=doc_id,
                chunk_kind="article",
                location=Location(kind="article", start=loc, end=loc, label=_label(jo, gaji, hang)),
                edition=edition,
                text=text,
            )
        )

    try:
        units = _as_list(data["법령"]["조문"]["조문단위"])
    except KeyError, TypeError:
        raise LawIndexError(f"{doc_id}: 법령.조문.조문단위가 없다") from None

    for art in units:
        # 장·절 제목(전문)은 조문이 아니다
        if art.get("조문여부") != "조문":
            continue
        jo = int(art["조문번호"])
        gaji = int(art.get("조문가지번호") or 0)
        body = _clean(art.get("조문내용", ""))
        if _DELETED_ARTICLE.match(body):
            continue
        head_m = _ARTICLE_HEAD.match(body)
        head = head_m.group(0) if head_m else body
        hangs = _as_list(art.get("항"))

        # 항번호가 있는 항들: 항마다 조각 하나 (조 제목 + 항 글 + 호·목 글)
        if hangs and all(h.get("항번호") for h in hangs):
            for h in hangs:
                ht = _clean(h.get("항내용", ""))
                if not ht or _is_deleted(ht):
                    continue
                add(jo, gaji, _hang_no(h["항번호"]), " ".join([head, ht, *_ho_texts(h.get("호"))]))
            continue

        # 항이 없거나 항번호 없이 호만: 조 하나가 조각 하나 (항 0)
        parts = [body]
        for h in hangs:
            ht = _clean(h.get("항내용", ""))
            if ht:
                parts.append(ht)
            parts.extend(_ho_texts(h.get("호")))
        add(jo, gaji, 0, " ".join(parts))
    return chunks


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except TypeError, ValueError:
        return None


def editions_for(files: dict[str, str]) -> dict[str, Edition]:
    """doc_id → 시행일(YYYYMMDD) 을 받아 판본을 붙인다. 법마다 시행일 순으로 줄 세운다."""
    out: dict[str, Edition] = {}
    by_law: dict[str, list[tuple[date, str]]] = {}
    for doc_id, raw in files.items():
        d = _parse_date(raw)
        if d is None:
            # 판본을 모르면 빈칸이 아니라 unverified
            out[doc_id] = Edition(status="unverified", label=doc_id)
            continue
        law = doc_id.rsplit("_", 2)[0]
        by_law.setdefault(law, []).append((d, doc_id))

    for law, items in by_law.items():
        items.sort()  # 번호(MST) 순이 아니라 시행일 순
        dates = [d for d, _ in items]
        if len(set(dates)) != len(dates):
            raise LawIndexError(f"{law}: 시행일이 같은 판이 둘 이상이다")
        for i, (d, doc_id) in enumerate(items):
            # 끝일 = 다음 판 시행일 하루 전, 마지막 판은 None(지금도 효력)
            to = items[i + 1][0] - timedelta(days=1) if i + 1 < len(items) else None
            out[doc_id] = Edition(
                status="confirmed", effective_from=d, effective_to=to, label=doc_id
            )
    return out


def build_index(
    raw_dir: str | Path, laws: list[str], index_version: str
) -> tuple[list[Chunk], int]:
    """원본 폴더 → (조각 목록, 설정에 없어 뺀 파일 수)."""
    if not is_index_version("law", index_version):
        raise LawIndexError(f"법령 색인 판 이름이 아니다: {index_version}")
    loaded: dict[str, dict] = {}
    skipped = 0
    for path in sorted(Path(raw_dir).glob("body_*.json")):
        law, doc_id = parse_raw_name(path.name)
        if law not in laws:
            skipped += 1
            continue
        loaded[doc_id] = json.loads(path.read_text(encoding="utf-8"))

    eds = editions_for(
        {
            d: str(data.get("법령", {}).get("기본정보", {}).get("시행일자", ""))
            for d, data in loaded.items()
        }
    )
    chunks = [c for d, data in loaded.items() for c in chunk_law(data, d, eds[d], index_version)]
    if skipped:
        logger.info("설정에 없는 법령 파일 %d개는 뺐다", skipped)
    if not chunks:
        # 목록이 비면 경고하고 실패로 끝낸다 (조용히 성공하지 않음)
        logger.warning("법령 조각이 0개다: %s, 법령 %s", raw_dir, laws)
        raise LawIndexError("법령 조각이 0개다")
    return chunks, skipped


def write_jsonl(chunks: list[Chunk], out: str | Path) -> None:
    """chunk_id 순으로 한 줄에 조각 하나. 같은 입력이면 같은 바이트. 있는 파일은 덮어쓰지 않는다."""
    p = Path(out)
    if p.exists():
        raise LawIndexError(f"이미 있는 파일이라 덮어쓰지 않는다 (새 설정이면 새 판): {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    lines = [c.model_dump_json() for c in sorted(chunks, key=lambda c: c.chunk_id)]
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.rename(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="법령 원본 JSON → 색인 조각 JSONL")
    ap.add_argument("--config", required=True, help="config/index/law-idx-v<N>.yaml")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    try:
        chunks, skipped = build_index(cfg["raw_dir"], cfg["laws"], cfg["index_version"])
        write_jsonl(chunks, cfg["out"])
    except LawIndexError as e:
        logger.error("%s", e)
        return 1
    unverified = sum(c.edition.status == "unverified" for c in chunks)
    logger.info(
        "만듦: %s (조각 %d개, 문서 %d개, 판본 모름 %d개, 뺀 파일 %d개)",
        cfg["out"],
        len(chunks),
        len({c.doc_id for c in chunks}),
        unverified,
        skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
