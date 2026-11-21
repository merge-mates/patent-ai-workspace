"""F2 근거 검토 정답 만들기: 법령 정답 + 법령 원문 + 판례 원문 -> evidence_cases.jsonl.

실제 질문(real)과 오류 주입 5종(종류마다 4개)을 만든다. 모양의 기준은 eval/f2/gold.py와
docs/evaluation/f2-evidence-gold.md. 같은 입력이면 같은 바이트이고, 있는 파일은 덮지 않으며,
재료가 모자라면 만들지 않고 멈춘다. 오류·로그에는 원문 글자를 싣지 않는다.
법령 조각과 판본은 색인을 만드는 코드(patent_ai.retrieval.law_index)를 그대로 써서 만든다.

실행:
  uv run python -m eval.f2.make_cases --law-gold <law_gold.jsonl> --law-raw data/raw/law \
      --prec-raw data/raw/prec --goldsets-root data/goldsets --checked-on 2026-11-22 \
      --out <goldsets_root>/tune/f2/evidence_cases.jsonl
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

from eval.common.errors import EvalError
from eval.common.goldset import read_goldset_version
from eval.f2.gold import (
    ERROR_KINDS,
    ExpectedFix,
    ExpectedSource,
    InjectedCase,
    RealCase,
    Reviewed,
    check_set_size,
    count_cases,
    load_f2_cases,
)
from eval.retrieval.gold import load_gold
from patent_ai.core.schemas.common import Evidence, Flag, Status, StatusValue
from patent_ai.core.schemas.legal_evidence import (
    AsOfSource,
    LegalClaim,
    LegalEvidenceBundle,
    LegalQuestion,
    LegalSource,
    LegalSourceKind,
    QuestionSource,
    Speaker,
    TextKind,
    summarize_bundle_status,
    summarize_claim_status,
)
from patent_ai.retrieval.law_index import (
    LawIndexError,
    chunk_law,
    editions_for,
    parse_raw_name,
)
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)

PER_KIND = 4  # 주입은 종류마다 정확히 4개
# 판마다 기간이 바뀐 특허법 조문 loc (기간 값은 원문에서 뽑는다)
DEADLINE_LOCS = (520001, 530001, 670201, 1321700)
_ALL_KINDS = [
    LegalSourceKind.STATUTE,
    LegalSourceKind.GUIDELINE,
    LegalSourceKind.PRECEDENT,
    LegalSourceKind.TRIAL,
]
_TITLE = re.compile(r"^제\d+조(?:의\d+)?\(([^)]*)\)")
_PERIOD = re.compile(r"\d+\s?(?:일|개월|년)")
_LABEL = re.compile(r"^(?P<law>\D*?)\s*제(?P<jo>\d+)조(?:의(?P<gaji>\d+))?(?P<rest>.*)$")
_TAG = re.compile(r"<[^>]*>")


class _Law:
    """법 하나(예: 특허법)의 판본들과 그 조각. 필요할 때 읽는다."""

    def __init__(self, law: str, files: dict[str, Path], index_version: str):
        self.law, self.files, self.iv = law, files, index_version
        raw: dict[str, dict] = {}
        for doc_id in sorted(files):
            raw[doc_id] = json.loads(files[doc_id].read_text(encoding="utf-8"))
        self.editions = editions_for(
            {
                d: str(r.get("법령", {}).get("기본정보", {}).get("시행일자", ""))
                for d, r in raw.items()
            }
        )
        self.chunks: dict[str, dict[int, Chunk]] = {}
        for doc_id, data in raw.items():
            chunks = chunk_law(data, doc_id, self.editions[doc_id], index_version)
            self.chunks[doc_id] = {c.location.start: c for c in chunks}

    def confirmed_docs(self) -> list[str]:
        """시행일 순(옛 -> 새)으로 판본을 아는 판."""
        ok = [d for d, e in self.editions.items() if e.status == "confirmed" and e.effective_from]
        return sorted(ok, key=lambda d: self.editions[d].effective_from)


class _Corpus:
    def __init__(self, law_raw: Path, index_version: str):
        by_law: dict[str, dict[str, Path]] = {}
        for p in sorted(law_raw.glob("body_*.json")):
            law, doc_id = parse_raw_name(p.name)
            by_law.setdefault(law, {})[doc_id] = p
        self._files, self._iv = by_law, index_version
        self._laws: dict[str, _Law] = {}

    def law_of(self, doc_id: str) -> _Law:
        key = doc_id.rsplit("_", 2)[0]
        if key not in self._files:
            raise EvalError(f"법령 원문 폴더에 {key} 파일이 없다")
        if key not in self._laws:
            self._laws[key] = _Law(key, self._files[key], self._iv)
        return self._laws[key]

    def chunk(self, doc_id: str, loc: int) -> Chunk:
        law = self.law_of(doc_id)
        found = law.chunks.get(doc_id, {}).get(loc)
        if found is None:
            # 정답과 원문이 어긋남: 글자는 싣지 않고 ID·위치만
            raise EvalError(f"정답의 조각이 원문에 없다: {doc_id} {loc}")
        return found


def _edition_text(c: Chunk) -> str:
    ed = c.edition
    end = ed.effective_to.isoformat() if ed.effective_to else "현행"
    return f"{c.doc_id} 시행 {ed.effective_from.isoformat()} ~ {end}"


def _evidence(c: Chunk, checked_on: date, *, loc_label: str | None = None, loc: int | None = None):
    """색인 조각 -> Evidence (F2 걷는 뼈대와 같은 모양). 없는 출처는 loc·라벨만 바꿔 만든다."""
    start = c.location.start if loc is None else loc
    return Evidence(
        document_id=c.doc_id,
        location=loc_label or c.location.label,
        raw_text=c.text,
        edition=_edition_text(c),
        checked_on=checked_on,
        chunk_id=f"{c.index_version}:{c.doc_id}:{start}",
        index_version=c.index_version,
    )


def _statute_source(identifier: str, ev: Evidence) -> LegalSource:
    return LegalSource(
        source_kind=LegalSourceKind.STATUTE,
        identifier=identifier,
        evidence=ev,
        status=Status(value=StatusValue.CONFIRMED, checked="법령 원문 조각 대조"),
    )


def _bundle(
    bundle_id: str,
    question: LegalQuestion,
    claim_text: str,
    source: LegalSource,
    checked_on: date,
    oa_id: str | None = None,
    rejection: int | None = None,
) -> LegalEvidenceBundle:
    # 근거 검토(모델)를 하기 전 모양: review 없음, 사람이 봐야 한다는 표시만
    claim = LegalClaim(
        no=1,
        text=claim_text,
        sources=[source],
        status=summarize_claim_status([source]),
        flags=[Flag.NEEDS_HUMAN_REVIEW],
    )
    return LegalEvidenceBundle(
        bundle_id=bundle_id,
        oa_id=oa_id,
        rejection=rejection,
        question=question,
        checked_on=checked_on,
        claims=[claim],
        status=summarize_bundle_status([claim]),
    )


def _user_question(text: str, kinds: list[LegalSourceKind]) -> LegalQuestion:
    return LegalQuestion(
        text=text,
        source=QuestionSource.USER_QUESTION,
        as_of=None,
        as_of_source=AsOfSource.NONE,
        source_kinds=kinds,
    )


_REVIEWED = Reviewed(by=None, date=None)


# ---------- 실제 질문 ----------


def _real_cases(law_gold: Path, corpus: _Corpus, gold_version: int) -> list[RealCase]:
    cases: list[RealCase] = []
    for row in load_gold(law_gold):
        ok = bool(row.items) and all(
            i.kind == "article"
            and i.gold_edition is not None
            and i.gold_edition.status == "confirmed"
            for i in row.items
        )
        if not ok or row.as_of is None:
            logger.warning(
                "법령 정답 줄 %s는 판본 미확정이거나 조문이 아닌 항목이 있어 뺐다", row.row_id
            )
            continue
        expects = []
        for i in row.items:
            doc_id = i.gold_edition.label
            if doc_id is None or i.start is None:
                raise EvalError(f"{row.row_id}: 정답 항목에 판 ID나 위치가 없다")
            corpus.chunk(doc_id, i.start)  # 원문에 조각이 있는지 확인 (없으면 멈춤)
            expects.append(
                ExpectedSource(
                    source_kind=LegalSourceKind.STATUTE,
                    identifier=i.label,
                    document_id=doc_id,
                    loc=i.start,
                    edition_status="confirmed",
                )
            )
        oa_id, rej = row.row_id.split(":")
        cases.append(
            RealCase(
                kind="real",
                gold_version=gold_version,
                case_id=f"real:{row.row_id}",
                reviewed=_REVIEWED,
                oa_id=oa_id,
                rejection=int(rej.removeprefix("r")),
                question=LegalQuestion(
                    text=row.query,
                    source=QuestionSource.OA_REJECTION,
                    as_of=row.as_of,
                    as_of_source=AsOfSource.OA_DISPATCH_DATE,
                    source_kinds=list(_ALL_KINDS),
                    article_refs=[i.label for i in row.items],
                ),
                expect_sources=expects,
            )
        )
    cases.sort(key=lambda c: c.case_id)
    return cases


def _base(real: RealCase, corpus: _Corpus, checked_on: date) -> tuple[Chunk, LegalSource, str]:
    """바탕 묶음의 근거: 실제 질문의 첫 정답 조문 조각."""
    es = real.expect_sources[0]
    chunk = corpus.chunk(es.document_id, es.loc)
    claim_text = (
        f"거절이유 근거 조문: {es.identifier} (OA 발송일 {real.question.as_of.isoformat()} 시행판)"
    )
    return chunk, _statute_source(es.identifier, _evidence(chunk, checked_on)), claim_text


def _inject(case_id, error, gold_version, base_id, bundle, fix) -> InjectedCase:
    return InjectedCase(
        kind="injected",
        gold_version=gold_version,
        case_id=case_id,
        reviewed=_REVIEWED,
        error=error,
        base_case_id=base_id,
        bundle=bundle,
        target_claim=1,
        target_source=0,
        fix=fix,
    )


def _base_bundle(real, case_id, claim_text, source, checked_on) -> LegalEvidenceBundle:
    return _bundle(
        f"lb:{case_id}", real.question, claim_text, source, checked_on, real.oa_id, real.rejection
    )


def _need(reals: list[RealCase]) -> list[RealCase]:
    if len(reals) < PER_KIND:
        raise EvalError(f"실제 질문이 {len(reals)}개다 (주입 바탕으로 {PER_KIND}개 필요)")
    return reals[:PER_KIND]


def _nonexistent(reals, corpus, checked_on, gv) -> list[InjectedCase]:
    out = []
    for n, real in enumerate(_need(reals), start=1):
        chunk, _, claim_text = _base(real, corpus, checked_on)
        es = real.expect_sources[0]
        m = _LABEL.match(es.identifier)
        loc = chunk.location.start
        jo, hang = loc // 10000, loc % 100
        # 그 법의 모든 판을 본다: 다른 판(예: 현행)에 있는 조문을 "없는 출처"로 내면 안 된다
        law = corpus.law_of(chunk.doc_id)
        have = {k // 100 for doc in law.chunks.values() for k in doc}
        # 같은 조의 가지 번호를 2부터 올려 어느 판에도 없는 첫 번호를 고른다
        g = next((g for g in range(2, 100) if jo * 100 + g not in have), None)
        if m is None or g is None:
            raise EvalError(f"{real.case_id}: 없는 가지 번호를 고를 수 없다")
        label = f"제{jo}조의{g}{m['rest']}"
        fake_loc = jo * 10000 + g * 100 + hang
        ev = _evidence(chunk, checked_on, loc_label=label, loc=fake_loc)
        src = _statute_source(f"{m['law']} {label}", ev)
        cid = f"inject:nonexistent_source:{n}"
        out.append(
            _inject(cid, "nonexistent_source", gv, real.case_id,
                    _base_bundle(real, cid, claim_text, src, checked_on), None)
        )  # fmt: skip
    return out


def _claim_mismatch(reals, corpus, checked_on, gv) -> list[InjectedCase]:
    out = []
    for n, real in enumerate(_need(reals), start=1):
        chunk, src, _ = _base(real, corpus, checked_on)
        es = real.expect_sources[0]
        chunks = corpus.law_of(chunk.doc_id).chunks[chunk.doc_id]
        # 바탕 조 다음으로 오는, 조 머리에 괄호 제목이 있는 조문
        title = None
        for loc in sorted(chunks):
            if loc // 100 > chunk.location.start // 100:
                m = _TITLE.match(chunks[loc].text)
                if m and m.group(1).strip():
                    title = m.group(1)
                    break
        if title is None:
            raise EvalError(f"{real.case_id}: 바탕 조 다음에 제목 있는 조문이 없다")
        cid = f"inject:claim_text_mismatch:{n}"
        text = f"{es.identifier}은(는) {title}에 관하여 정한다."
        out.append(
            _inject(cid, "claim_text_mismatch", gv, real.case_id,
                    _base_bundle(real, cid, text, src, checked_on), None)
        )  # fmt: skip
    return out


def _other_edition(reals, corpus, checked_on, gv) -> list[InjectedCase]:
    out = []
    for n, real in enumerate(_need(reals), start=1):
        chunk, _, claim_text = _base(real, corpus, checked_on)
        es = real.expect_sources[0]
        law = corpus.law_of(chunk.doc_id)
        has = [d for d in law.confirmed_docs() if chunk.location.start in law.chunks[d]]
        others = [d for d in has if d != es.document_id]
        if not others:
            raise EvalError(f"{real.case_id}: 같은 위치가 있는 다른 판이 없다")
        # 가장 늦은 판. 그게 정답 판이면 가장 이른 다른 판
        pick = others[0] if has[-1] == es.document_id else others[-1]
        other = law.chunks[pick][chunk.location.start]
        src = _statute_source(es.identifier, _evidence(other, checked_on))
        cid = f"inject:other_edition_asserted:{n}"
        out.append(
            _inject(cid, "other_edition_asserted", gv, real.case_id,
                    _base_bundle(real, cid, claim_text, src, checked_on),
                    ExpectedFix(document_id=es.document_id))
        )  # fmt: skip
    return out


# ---------- 판례 ----------


def _clean_summary(s) -> str:
    # 태그를 지우고 공백을 하나로
    return " ".join(_TAG.sub("", s).split()) if isinstance(s, str) else ""


def _precs(prec_raw: Path) -> list[dict]:
    found = []
    for p in sorted(prec_raw.glob("body_*.json")):
        stem = p.stem.removeprefix("body_")
        if "_" not in stem:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))["PrecService"]
            decided = datetime.strptime(str(d["선고일자"]), "%Y%m%d").date()
            no, court = str(d["사건번호"]).strip(), str(d["법원명"]).strip()
        except KeyError, TypeError, ValueError, json.JSONDecodeError:
            logger.warning("판례 원문 %s를 읽을 수 없어 뺐다", p.name)
            continue
        summary = _clean_summary(d.get("판결요지"))
        if no and court and summary:
            found.append(
                {"no": no, "serial": stem.rsplit("_", 1)[1], "court": court, "date": decided,
                 "summary": summary}
            )  # fmt: skip
    found.sort(key=lambda x: (x["no"], x["serial"]))
    return found


def _summary_as_full(prec_raw, checked_on, gv) -> list[InjectedCase]:
    precs = _precs(prec_raw)
    if len(precs) < PER_KIND:
        raise EvalError(f"판결요지가 있는 판례가 {len(precs)}개다 ({PER_KIND}개 필요)")
    out = []
    for n, p in enumerate(precs[:PER_KIND], start=1):
        ev = Evidence(
            document_id=f"prec:{p['serial']}",
            location="전문",
            raw_text=p["summary"],  # 요지를 전문이라고 우긴 근거
            checked_on=checked_on,
        )
        src = LegalSource(
            source_kind=LegalSourceKind.PRECEDENT,
            identifier=p["no"],
            evidence=ev,
            status=Status(value=StatusValue.CONFIRMED, checked="판례 원문 대조"),
            text_kind=TextKind.FULL,
            speaker=Speaker.COURT,
            decided_on=p["date"],
            court=p["court"],
        )
        cid = f"inject:summary_as_full:{n}"
        q = _user_question(
            f"{p['court']} {p['no']} 판결은 무엇을 판단했는가", [LegalSourceKind.PRECEDENT]
        )
        b = _bundle(
            f"lb:{cid}",
            q,
            f"{p['court']} {p['no']} 판결 전문은 다음과 같이 판단했다.",
            src,
            checked_on,
        )
        out.append(
            _inject(cid, "summary_as_full", gv, None, b, ExpectedFix(text_kind=TextKind.SUMMARY))
        )
    return out


# ---------- 옛 기한 ----------


def _period(c: Chunk) -> str | None:
    m = _PERIOD.search(c.text)
    return m.group(0) if m else None


def _old_deadline(corpus, checked_on, gv) -> list[InjectedCase]:
    law_key = "특허법"
    docs = [d for d in corpus._files.get(law_key, {})]
    if not docs:
        raise EvalError("법령 원문 폴더에 특허법 파일이 없다")
    law = corpus.law_of(docs[0])
    ordered = law.confirmed_docs()
    cur_i = next(
        (
            i
            for i, d in enumerate(ordered)
            if law.editions[d].effective_from <= checked_on
            and (law.editions[d].effective_to is None or law.editions[d].effective_to >= checked_on)
        ),
        None,
    )
    if cur_i is None:
        raise EvalError("확인일에 시행 중인 특허법 판이 없다")
    cur_doc = ordered[cur_i]
    out = []
    for n, loc in enumerate(DEADLINE_LOCS, start=1):
        cur = law.chunks[cur_doc].get(loc)
        cur_period = _period(cur) if cur else None
        if cur is None or cur_period is None:
            raise EvalError(f"현행 판 {cur_doc}에서 {loc}의 기간을 읽을 수 없다")
        old = None
        for d in reversed(ordered[:cur_i]):  # 현행 바로 앞에서부터 거꾸로
            c = law.chunks[d].get(loc)
            p = _period(c) if c else None
            if c is not None and p is not None and p != cur_period:
                old, old_period = c, p
                break
        if old is None:
            raise EvalError(f"{loc}: 현행과 기간이 다른 옛 판을 찾을 수 없다")
        label = f"{law_key} {cur.location.label}"
        src = _statute_source(label, _evidence(old, checked_on))
        cid = f"inject:old_deadline_as_current:{n}"
        q = _user_question(f"현행 특허법 {cur.location.label}의 기간은?", [LegalSourceKind.STATUTE])
        b = _bundle(
            f"lb:{cid}", q, f"현행 특허법 {cur.location.label}의 기간은 {old_period}이다.", src,
            checked_on,
        )  # fmt: skip
        out.append(
            _inject(cid, "old_deadline_as_current", gv, None, b,
                    ExpectedFix(document_id=cur_doc, raw_text_contains=cur_period))
        )  # fmt: skip
    return out


# ---------- 전체 ----------


def make_cases(
    law_gold: Path,
    law_raw: Path,
    prec_raw: Path,
    gold_version: int,
    checked_on: date,
    index_version: str,
) -> list[RealCase | InjectedCase]:
    corpus = _Corpus(law_raw, index_version)
    reals = _real_cases(law_gold, corpus, gold_version)
    injected = [
        *_nonexistent(reals, corpus, checked_on, gold_version),
        *_claim_mismatch(reals, corpus, checked_on, gold_version),
        *_other_edition(reals, corpus, checked_on, gold_version),
        *_summary_as_full(prec_raw, checked_on, gold_version),
        *_old_deadline(corpus, checked_on, gold_version),
    ]
    return sorted([*reals, *injected], key=lambda c: c.case_id)


def write_cases(cases, out: Path, gold_version: int) -> None:
    """쓰기 전에 gold.py 검사(load + 세트 크기)를 통과시킨다. 실패면 out을 만들지 않는다."""
    if out.exists():
        raise EvalError(f"이미 있는 파일이라 덮어쓰지 않는다: {out}")
    tmp = out.with_suffix(out.suffix + ".tmp")
    if tmp.exists():
        raise EvalError(f"임시 파일이 남아 있다. 확인 뒤 지운다: {tmp}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(c.model_dump_json() for c in cases) + "\n", encoding="utf-8")
    try:
        check_set_size(load_f2_cases(tmp, gold_version))
    except EvalError:
        tmp.unlink()
        raise
    tmp.rename(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F2 근거 검토 정답 만들기")
    ap.add_argument("--law-gold", required=True, type=Path)
    ap.add_argument("--law-raw", required=True, type=Path)
    ap.add_argument("--prec-raw", required=True, type=Path)
    ap.add_argument("--goldsets-root", required=True, type=Path)
    ap.add_argument("--checked-on", required=True, help="확인 기준일 YYYY-MM-DD")
    ap.add_argument("--index-version", default="law-idx-v2")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        checked_on = date.fromisoformat(args.checked_on)
    except ValueError:
        print("실패: --checked-on은 YYYY-MM-DD")
        return 1
    try:
        version = read_goldset_version(args.goldsets_root)
        cases = make_cases(
            args.law_gold, args.law_raw, args.prec_raw, version, checked_on, args.index_version
        )
        write_cases(cases, args.out, version)
    except (EvalError, LawIndexError) as e:
        print(f"실패: {e}")
        return 1
    c = count_cases(cases)
    kinds = " ".join(f"{e}={c[e]}" for e in ERROR_KINDS)
    print(f"만듦: {args.out} 합계 {c['total']} (real={c['real']} {kinds}), gold_version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
