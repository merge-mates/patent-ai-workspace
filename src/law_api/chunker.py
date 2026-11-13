"""법령 JSON을 조문·항·호·목 단위의 정규화된 구조로 바꾼다."""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional, Sequence

_MST_RE = re.compile(r"_(\d+)_(\d{8})\.json$")
_ARTICLE_DELETED_RE = re.compile(r"^제\d+조(?:의\d+)?\s+삭제\s*<")
_PARAGRAPH_DELETED_RE = re.compile(r"^\S+\s+삭제\s*<")
_HEADING_RE = re.compile(r"^제\d+(장|절|관)(?:의\d+)?")
_TRAILING_TAG_RE = re.compile(r"(?:\s*<[^<>]*>)+\s*$")
_HEADING_LEVELS = {"장": "chapter", "절": "section", "관": "subsection"}
_HO_LINE_RE = re.compile(r"^\d+(?:의\d+)?\.\s")
_AMEND_TAG_RE = re.compile(r"\s*<[^<>]*\d{4}\.\d{1,2}\.\d{1,2}[^<>]*>")


@dataclass(frozen=True)
class Paragraph:
    number: Optional[str]
    lines: tuple[str, ...]
    deleted: bool


@dataclass(frozen=True)
class Article:
    label: str
    number: int
    branch: Optional[int]
    title: str
    lead: str
    paragraphs: tuple[Paragraph, ...]
    deleted: bool
    source_key: str
    effective_date: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None


@dataclass(frozen=True)
class Law:
    name: str
    mst: Optional[str]
    effective_date: str
    articles: tuple[Article, ...]


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _text(item: dict, key: str) -> str:
    parts = _flatten(item.get(key))
    return "\n".join(parts)


def _flatten(value: Any) -> list[str]:
    """문자열 또는 (중첩) 리스트를 strip한 비어 있지 않은 문자열 목록으로 편다."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [s for v in value for s in _flatten(v)]
    raise TypeError(f"문자열 또는 리스트가 아닌 내용: {type(value).__name__}")


def _live_lines(value: Any) -> list[str]:
    """호·목 내용을 줄로 펴되, `번호 삭제 <날짜>` 꼴의 삭제 줄은 뺀다(개정 태그를 지우기 전 원문 기준)."""
    return [ln for ln in _flatten(value) if not _PARAGRAPH_DELETED_RE.match(ln)]


def _normalize_paragraph(raw: dict) -> Paragraph:
    lines: list[str] = []
    head = _text(raw, "항내용")
    if head:
        lines.append(head)
    for ho in _as_list(raw.get("호")):
        lines.extend(_live_lines(ho.get("호내용")))
        for mok in _as_list(ho.get("목")):
            lines.extend(_live_lines(mok.get("목내용")))
    return Paragraph(
        number=_text(raw, "항번호") or None,
        lines=tuple(lines),
        deleted=bool(head and _PARAGRAPH_DELETED_RE.match(head)),
    )


def _strip_prefix(content: str, label: str, title: str) -> str:
    """`제N조[의M](제목)` 접두를 떼고 strip한다. 제목이 없으면 strip만 한다."""
    content = content.strip()
    if not title:
        return content
    match = re.match(rf"^{re.escape(label)}\({re.escape(title)}\)", content)
    return content[match.end():].strip() if match else content


def normalize_article(unit: dict) -> Article:
    number = int(unit["조문번호"])
    branch_raw = _text(unit, "조문가지번호")
    branch = int(branch_raw) if branch_raw else None
    label = f"제{number}조" + (f"의{branch}" if branch is not None else "")
    content = _text(unit, "조문내용")
    raw_paragraphs = _as_list(unit.get("항"))

    deleted = bool(_ARTICLE_DELETED_RE.match(content)) and not raw_paragraphs
    title = "" if deleted else _text(unit, "조문제목")
    lead = "" if deleted else _strip_prefix(content, label, title)

    return Article(
        label=label,
        number=number,
        branch=branch,
        title=title,
        lead=lead,
        paragraphs=tuple(_normalize_paragraph(p) for p in raw_paragraphs),
        deleted=deleted,
        source_key=_text(unit, "조문키"),
        effective_date=_text(unit, "조문시행일자"),
    )


def parse_heading(text: str) -> tuple[str, str]:
    """장·절·관 제목을 `(level, cleaned)`로 나눈다. 인식하지 못하면 ValueError."""
    cleaned = _TRAILING_TAG_RE.sub("", text.strip()).strip()
    match = _HEADING_RE.match(cleaned)
    if not match:
        raise ValueError(f"장·절·관 제목을 인식하지 못함: {text!r}")
    return _HEADING_LEVELS[match.group(1)], cleaned


def load_law(path: Path) -> Law:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)["법령"]
    info = data["기본정보"]
    match = _MST_RE.search(path.name)
    units = _as_list((data.get("조문") or {}).get("조문단위"))
    articles: list[Article] = []
    place: dict[str, Optional[str]] = {"chapter": None, "section": None, "subsection": None}
    for unit in units:
        kind = unit.get("조문여부")
        if kind == "전문":
            level, cleaned = parse_heading(_text(unit, "조문내용"))
            place[level] = cleaned
            if level == "chapter":
                place["section"] = place["subsection"] = None
            elif level == "section":
                place["subsection"] = None
        elif kind == "조문":
            articles.append(replace(normalize_article(unit), **place))
    return Law(
        name=info["법령명_한글"],
        mst=match.group(1) if match else None,
        effective_date=str(info["시행일자"]),
        articles=tuple(articles),
    )


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    metadata: dict


def strip_amend_tags(text: str) -> str:
    """날짜가 든 꺾쇠 태그(<개정 2014.6.11> 등)를 지운다. <별표 1> 같은 날짜 없는 꺾쇠는 남긴다."""
    return _AMEND_TAG_RE.sub("", text).rstrip()


def _circled_to_int(label: Optional[str]) -> Optional[int]:
    """원문자 항번호(①~㊿)를 정수로. 원문자가 아니면 None."""
    if not label or len(label) != 1:
        return None
    o = ord(label)
    if 0x2460 <= o <= 0x2473:  # ①~⑳
        return o - 0x245F
    if 0x3251 <= o <= 0x325F:  # ㉑~㉟
        return 21 + o - 0x3251
    if 0x32B1 <= o <= 0x32BF:  # ㊱~㊿
        return 36 + o - 0x32B1
    return None


def _make_chunk(law: Law, art: Article, chunk_id: str, lines: list[str], strategy: str,
                paragraph_no: Optional[int] = None) -> Chunk:
    text = "\n".join(lines)
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        metadata={
            "law_name": law.name, "law_mst": law.mst,
            "law_effective_date": law.effective_date,
            "label": art.label, "article_no": art.number, "branch_no": art.branch,
            "title": art.title, "chapter": art.chapter, "section": art.section,
            "subsection": art.subsection, "source_key": art.source_key,
            "char_len": len(text), "strategy": strategy,
            **({"paragraph_no": paragraph_no} if strategy == "paragraph" else {}),
        },
    )


def _split_long(law: Law, art: Article, chunk_id: str, lines: list[str], strategy: str, paragraph_no: Optional[int],
                max_chars: Optional[int]) -> list[Chunk]:
    """텍스트가 max_chars 를 넘는 청크를 호(`1.`, `1의2.`) 경계에서 나눈다(목은 앞 호에 붙임).

    조각마다 앞부분(첫 호 앞의 줄: 머리글·머리말·항 첫 줄)을 반복하고, id 는 `<원래 id>#1`, `#2`…,
    메타데이터에 part/parts 를 넣는다. 호 줄이 없거나 나눌 필요가 없으면 청크 1개 그대로.
    하나의 호가 혼자서 max_chars 를 넘으면 그 호는 쪼개지 않는다.
    """
    whole = _make_chunk(law, art, chunk_id, lines, strategy, paragraph_no)
    if max_chars is None or len(whole.text) <= max_chars:
        return [whole]
    first = next((i for i, ln in enumerate(lines) if _HO_LINE_RE.match(ln)), None)
    if first is None:
        return [whole]
    prefix, units = lines[:first], []
    for ln in lines[first:]:
        if _HO_LINE_RE.match(ln) or not units:
            units.append([ln])
        else:
            units[-1].append(ln)
    groups: list[list[str]] = [[]]
    size = len("\n".join(prefix))
    for unit in units:
        add = len("\n".join(unit)) + 1
        if groups[-1] and size + add > max_chars:
            groups.append([])
            size = len("\n".join(prefix))
        groups[-1].extend(unit)
        size += add
    if len(groups) == 1:
        return [whole]
    out = []
    for i, g in enumerate(groups, start=1):
        c = _make_chunk(law, art, f"{chunk_id}#{i}", prefix + g, strategy, paragraph_no)
        c.metadata.update({"part": i, "parts": len(groups)})
        out.append(c)
    return out


def build_chunks(law: Law, *, strategy: str = "article", strip_tags: bool = False,
                 max_chars: Optional[int] = None) -> list[Chunk]:
    """strategy: "article"(조문 1개 = 청크 1개) | "paragraph"(살아있는 항이 2개 이상인 조문만 항마다 청크 1개).

    paragraph 의 항 청크 id 는 `법령#제29조#제1항`, 나누지 않는 조문은 `법령#제29조`.
    항 청크 텍스트는 조문 머리글(`법령 제N조(제목)`) + 머리말(있으면) + 그 항의 줄(호·목 포함).
    """
    if strategy not in ("article", "paragraph"):
        raise ValueError(f"지원하지 않는 strategy: {strategy!r} ('article', 'paragraph')")
    clean = strip_amend_tags if strip_tags else (lambda t: t)

    def cleaned_lines(raws) -> list[str]:
        out = []
        for raw in raws:
            c = clean(raw)
            if c.strip():
                out.append(c)
        return out

    chunks: list[Chunk] = []
    for art in law.articles:
        if art.deleted:
            continue
        header = f"{law.name} {art.label}({art.title})"
        lead = [art.lead] if art.lead else []
        live = [para for para in art.paragraphs if not para.deleted]
        if strategy == "paragraph" and len(live) >= 2:
            seen: set[int] = set()
            for pos, para in enumerate(art.paragraphs, start=1):
                if para.deleted:
                    continue
                no = _circled_to_int(para.number) or pos
                if no in seen:
                    raise ValueError(f"{art.label}: 항 번호 {no} 가 중복됩니다.")
                seen.add(no)
                lines = [header] + cleaned_lines(lead + list(para.lines))
                chunks.extend(_split_long(law, art, f"{law.name}#{art.label}#제{no}항", lines, strategy, no, max_chars))
            continue
        lines = [header] + cleaned_lines(lead + [ln for para in live for ln in para.lines])
        chunks.append(_make_chunk(law, art, f"{law.name}#{art.label}", lines, strategy))
    return chunks


def write_jsonl(chunks: list[Chunk], path: Path) -> None:
    """청크를 한 줄에 하나씩 UTF-8 JSONL로 쓴다. 같은 입력이면 바이트가 같다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for c in chunks:
            row = {"chunk_id": c.chunk_id, "text": c.text, "metadata": c.metadata}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _output_name(input_path: Path, strip_tags: bool, strategy: str = "article", max_chars: Optional[int] = None) -> str:
    stem = input_path.name
    if stem.startswith("body_"):
        stem = stem[len("body_"):]
    if stem.endswith(".json"):
        stem = stem[: -len(".json")]
    return f"chunks_{stem}{'_notags' if strip_tags else ''}{'_paragraph' if strategy == 'paragraph' else ''}{f'_split{max_chars}' if max_chars else ''}.jsonl"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="chunker", description="법령 JSON을 청크 JSONL로 변환한다.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--strip-tags", action="store_true")
    parser.add_argument("--strategy", choices=["article", "paragraph"], default="article")
    parser.add_argument("--max-chars", type=int, default=None,
                        help="(paragraph 전용) 이 글자 수를 넘는 항 청크를 호 경계에서 나눔")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    src = args.input.resolve()
    out_dir = args.out_dir.resolve()
    if out_dir == src.parent or src.parent in out_dir.parents:
        print(f"오류: --out-dir({args.out_dir})이 입력 파일 폴더이거나 그 아래입니다. 원본 폴더에는 쓰지 않습니다.",
              file=sys.stderr)
        return 2
    try:
        law = load_law(args.input)
        chunks = build_chunks(law, strategy=args.strategy, strip_tags=args.strip_tags, max_chars=args.max_chars)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    out = out_dir / _output_name(args.input, args.strip_tags, args.strategy, args.max_chars)
    write_jsonl(chunks, out)
    lens = sorted(len(c.text) for c in chunks)
    n = len(lens)
    print(f"법령: {law.name}")
    print(f"판본: MST {law.mst}, 시행일 {law.effective_date}")
    print(f"조문 수: {len(law.articles)}")
    print(f"삭제 제외: {sum(1 for a in law.articles if a.deleted)}")
    print(f"청크 수: {n}")
    if n:
        print(f"청크 길이: 중앙값 {statistics.median(lens):g}, p90 {lens[int(0.9 * (n - 1))]}, 최대 {lens[-1]}")
    print(f"출력: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
