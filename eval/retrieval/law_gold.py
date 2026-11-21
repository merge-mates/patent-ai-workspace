"""법령 정답 변환: 검수한 검색 정답 json + OA 글 → 법령 정답 파일 (#66 task 2).

한 줄 = OA 거절이유 하나. 질의는 그 거절이유 본문에서 조문 표기를 [조문]으로 가린 글.
정답 항목은 거절이유가 짚은 조문(6자리 위치 번호)과 그 법령의 적용 판본.
판본을 못 찾은 항목은 unverified로 두고, 채점기가 그 줄을 분모에서 뺀다 (재아 11/19 규칙).
찾은 판의 시행 시작일이 발송일 뒤인 항목도 unverified로 두고 경고한다 (#129):
그 판은 그날 검색 범위에 없어서 검색기가 못 찾고, 그게 "못 찾은 질문"처럼 보이면 안 된다.

실행:
  uv run python -m eval.retrieval.law_gold --gold-json <검수 정답.json> \
      --oa-dir data/raw/oa_txt_tune --out <goldsets_root>/tune/retrieval/law_gold.jsonl
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

from eval.retrieval.checks import find_leaks
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldItem, GoldRow
from patent_ai.retrieval.law_index import article_loc
from patent_ai.retrieval.schemas import Edition

logger = logging.getLogger(__name__)

_BODY_START = "[구체적인 거절이유]"
# 본문 끝: [첨 부] 또는 << 안내 >> (그 뒤 번호 붙은 안내문을 거절이유로 자르지 않게)
_BODY_END = re.compile(r"^(?:\[첨\s*부\]|<<\s*안내\s*>>)")
# 심사관 서명 줄("… 심사관 홍길동")과 그 앞 부서 줄: 사람 이름을 질의에 넣지 않는다
_SIGNATURE = re.compile(r"심사관\s+\S{2,5}\s*$")
_DEPARTMENT = re.compile(r"심사(?:국|과|팀|부)\s*$")
# 거절이유 순번 제목: 줄 맨 앞(들여쓰기 없음)의 "1. " (표 안 번호 줄은 들여써 있다)
_REASON_HEAD = re.compile(r"^([1-9][0-9]*)\.\s")
# [심사결과] 요약 표: 머리 줄과 순번 줄("    1        특허법 제29조제2항"처럼 들여쓴 숫자 뒤 칸)
_SUMMARY_HEAD = re.compile(r"순번\s+거절이유가\s*있는\s*부분")
_SUMMARY_ROW = re.compile(r"^\s{0,12}(\d{1,2})\s{3,}\S")
# 조문 표기: (특허법|같은 법 [시행령]) 제29조[의2][제1항][제2호], "29조 2항"처럼 '제'가 없어도
_ARTICLE_REF = re.compile(
    r"(?:(?:특허법|같은\s*법|동법)\s*(?:시행령|시행규칙)?\s*)?"
    r"제?\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*제?\s*\d+\s*항)?(?:\s*제?\s*\d+\s*호)?"
)
# 정답 조문 문자열 하나: 특허법 [시행령] 제42조[의2][제4항][제2호]
_GOLD_ARTICLE = re.compile(
    r"^(?P<law>특허법(?:\s*시행령)?)\s*제(?P<jo>\d+)조(?:의(?P<gaji>\d+))?"
    r"(?:제(?P<hang>\d+)항)?(?:제(?P<ho>\d+)호)?$"
)
# 적용판본 문자열 속 판: 특허법_212229_20200311, 시행령_193953_20170603
_EDITION = {
    "특허법": re.compile(r"(?<![가-힣_])특허법_(\d+)_(\d{8})"),
    "특허법_시행령": re.compile(r"시행령_(\d+)_(\d{8})"),
}


class LawGoldError(RetrievalEvalError):
    """법령 정답을 만들 수 없다."""


def _count_in_summary(head_lines: list[str]) -> int | None:
    """[심사결과] 요약 표의 순번 줄 수. 표 머리("순번 거절이유가 있는 부분")를 못 찾으면 None."""
    try:
        i = next(k for k, ln in enumerate(head_lines) if _SUMMARY_HEAD.search(ln))
    except StopIteration:
        return None
    n = 0
    for ln in head_lines[i + 1 :]:
        if ln.strip().startswith("□"):  # 다음 칸("□ 특허 가능한 청구항")에서 표가 끝난다
            break
        m = _SUMMARY_ROW.match(ln)
        if m and int(m.group(1)) == n + 1:
            n += 1
    return n or None


def segment_reasons(oa_text: str) -> dict[int, str]:
    """OA 글 → {거절이유 순번: 그 본문}. 순번 제목이 없으면 본문 전체가 1번."""
    lines = oa_text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if _BODY_START in ln) + 1
    except StopIteration:
        raise LawGoldError("OA 글에 [구체적인 거절이유] 표시가 없다") from None
    body: list[str] = []
    for ln in lines[start:]:
        if _BODY_END.match(ln.strip()) or _SIGNATURE.search(ln):
            break
        body.append(ln)
    # 서명 바로 앞의 부서 줄·빈 줄도 뺀다
    while body and (not body[-1].strip() or _DEPARTMENT.search(body[-1])):
        body.pop()

    # 요약 표에 적힌 거절이유 수. 본문 속 "1. 청구항5 …" 같은 번호 목록을
    # 거절이유 제목으로 잘못 세지 않게, 이 수만큼만 제목으로 본다 (#214)
    limit = _count_in_summary(lines[: start - 1])

    # 1, 2, 3 … 차례로 나오는 줄만 제목으로 본다 (본문 속 다른 번호 줄에 안 속게)
    heads: list[tuple[int, int]] = []
    for i, ln in enumerate(body):
        if limit is not None and len(heads) >= limit:
            break
        m = _REASON_HEAD.match(ln)
        if m and int(m.group(1)) == len(heads) + 1:
            heads.append((len(heads) + 1, i))
    # 거절이유가 하나뿐이면 제목 줄 앞 머리말도 그 이유 본문이다: 전체를 1번으로
    if not heads or limit == 1:
        return {1: "\n".join(body).strip()}
    out: dict[int, str] = {}
    for n, (no, i) in enumerate(heads):
        end = heads[n + 1][1] if n + 1 < len(heads) else len(body)
        out[no] = "\n".join(body[i:end]).strip()
    return out


def mask_articles(text: str) -> str:
    """조문 표기를 [조문]으로 바꾼다. 청구항 번호(청구항 제13항)는 그대로 둔다."""
    return _ARTICLE_REF.sub("[조문]", text)


def parse_articles(spec: str) -> list[tuple[str, int, str]]:
    """'특허법 제42조제8항, 특허법 시행령 제5조제6항' → [(법령 키, 위치 번호, 표기)]."""
    out = []
    for part in (p.strip() for p in spec.split(",")):
        m = _GOLD_ARTICLE.match(part)
        if not m:
            raise LawGoldError(f"조문 표기를 읽을 수 없다: {part!r}")
        law = "특허법_시행령" if "시행령" in m["law"] else "특허법"
        # 호는 위치 번호에 넣지 않는다: 호는 그 항 조각 안에 있다 (항 단위 청킹)
        loc = article_loc(int(m["jo"]), int(m["gaji"] or 0), int(m["hang"] or 0))
        out.append((law, loc, part))
    return out


def edition_for(applied: dict, law: str) -> Edition:
    """사건의 적용판본 칸들에서 그 법령의 판을 찾는다. 못 찾으면 unverified."""
    pattern = _EDITION.get(law)
    for value in applied.values() if pattern else []:
        m = pattern.search(str(value))
        if m:
            d = datetime.strptime(m.group(2), "%Y%m%d").date()
            return Edition(
                status="confirmed", effective_from=d, label=f"{law}_{m.group(1)}_{m.group(2)}"
            )
    return Edition(status="unverified")


def _in_scope_edition(ed: Edition, as_of: date, row_id: str) -> Edition:
    """정답 판의 시행 시작일이 기준일(발송일) 뒤면 unverified로 바꾸고 경고한다.

    검색기는 발송일에 시행 중인 판만 보므로, 그 판은 범위에 없어 맞힐 수 없다.
    시작일이 발송일과 같으면 그날 시행 중이라 그대로 둔다. 로그에는 row_id와 판 이름만 쓴다.
    """
    if ed.status != "confirmed" or ed.effective_from is None or ed.effective_from <= as_of:
        return ed
    logger.warning(
        "정답 판본이 발송일 뒤라 unverified로 둔다: %s (%s, 시행 %s > 발송일 %s)",
        row_id,
        ed.label,
        ed.effective_from,
        as_of,
    )
    return Edition(status="unverified", label=ed.label)


def convert(cases: list[dict], oa_dir: str | Path) -> tuple[list[GoldRow], int]:
    """사건 목록 → (정답 줄, 못 만든 거절이유 수). 못 만든 것은 발송번호만 로그에 남긴다."""
    rows: list[GoldRow] = []
    skipped = 0
    for case in cases:
        oa_no = case["발송번호"]
        reasons = case["거절이유"]
        path = Path(oa_dir) / f"{case['출원번호']}_OA_{oa_no}.txt"
        if not path.is_file():
            logger.warning("OA 글이 없어 뺀다: 발송번호 %s (%d건)", oa_no, len(reasons))
            skipped += len(reasons)
            continue
        segs = segment_reasons(path.read_text(encoding="utf-8"))
        if sorted(segs) != sorted(r["순번"] for r in reasons):
            # 자른 순번이 정답 순번과 다르면 어느 글이 어느 이유인지 모른다: 사건째 뺀다
            logger.warning(
                "거절이유 자르기가 정답 순번과 안 맞아 뺀다: 발송번호 %s (자름 %d, 정답 %d)",
                oa_no,
                len(segs),
                len(reasons),
            )
            skipped += len(reasons)
            continue
        as_of = datetime.strptime(case["발송일"], "%Y-%m-%d").date()
        for r in reasons:
            row_id = f"{oa_no}:r{r['순번']}"
            items = [
                GoldItem(
                    kind="article",
                    start=loc,
                    end=loc,
                    label=label,
                    gold_edition=_in_scope_edition(
                        edition_for(case["적용판본"], law), as_of, row_id
                    ),
                )
                for law, loc, label in parse_articles(r["조문"])
            ]
            row = GoldRow(
                row_id=row_id,
                corpus="law",
                query=mask_articles(segs[r["순번"]]),
                doc_ids=None,
                as_of=as_of,
                items=items,
            )
            # 가린 뒤에도 정답 조 번호가 남으면 쓰지 않는다 (채점기가 어차피 막음)
            if find_leaks(row):
                logger.warning("조문 표기가 남아 뺀다: %s", row.row_id)
                skipped += 1
                continue
            rows.append(row)
    return rows, skipped


def write_gold(rows: list[GoldRow], out: str | Path) -> None:
    """한 줄에 정답 줄 하나. 0줄이면 쓰지 않고 멈춘다. 있는 파일은 덮어쓰지 않는다."""
    if not rows:
        logger.warning("법령 정답 줄이 0개다")
        raise LawGoldError("법령 정답 줄이 0개다")
    p = Path(out)
    if p.exists():
        raise LawGoldError(f"이미 있는 파일이라 덮어쓰지 않는다: {p.name}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="검수 정답 json + OA 글 → 법령 정답 jsonl")
    ap.add_argument("--gold-json", required=True)
    ap.add_argument("--oa-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cases = json.loads(Path(args.gold_json).read_text(encoding="utf-8"))["사건"]
    try:
        rows, skipped = convert(cases, args.oa_dir)
        write_gold(rows, args.out)
    except LawGoldError as e:
        logger.error("%s", e)
        return 1
    unverified = sum(not r.edition_confirmed() for r in rows)
    logger.info(
        "만듦: %s (줄 %d개, 판본 모르는 줄 %d개, 못 만든 거절이유 %d개)",
        args.out,
        len(rows),
        unverified,
        skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
