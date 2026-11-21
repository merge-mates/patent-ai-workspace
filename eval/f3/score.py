"""F3 채점 (lane B9). 지정 번호를 입력에 주지 않고 돌린 F3 결과를 정답과 맞춘다.

지표
① 심사관 지정 위치 회수율: 검색 정답(cite_gold) 줄마다, F3가 그 청구항 × 인용문헌에서
   - 검색 단계가 가져온 조각(search_log, 구성요소별 상위 k의 합집합) -> search_hit / search_recall
   - 모델이 근거로 고른 조각(rows의 "AI 찾음" evidence) -> selected_hit / selected_recall
   이 정답 위치와 겹치는지 (겹침 규칙은 검색 채점기의 CiteMatcher 그대로, search-gold.md 2절 3번).
   예측에 "심사관 지정" 줄이 있으면 지정 번호를 준 실행이라 오염이다. 채점을 멈춘다.
② 신규성 한 문헌 규칙 위반 수 (failures.novelty_multi_citation, 0이어야 한다).
③ 명확성 문구 위치 일치: F1 정답 clarity_terms가 OA 당시 청구항 글자에서 나오는 자리와
   예측 claim_location의 글자 범위가 겹치는지 (f3-compare-gold.md 1절).
사람 검수 정답이 필요한 지표는 재지 않고 skipped_metrics에 "정답 없음"으로 남긴다.
못 찾은 질문(CQ): 검색 단계가 정답 위치를 하나도 못 덮은 (청구항, 인용문헌) 질문을 git 밖에 쌓는다.

scores에는 출원번호·발송번호·원문 글자를 넣지 않는다 (건수와 비율만).
명령: uv run python eval/run_eval.py --config <설정> --predictions <폴더> [--chunks <조각 JSONL>]
- 예측: <폴더>/<출원번호>_<발송번호>.f3.json (F3Result dump)
- 청구항 글자: 같은 폴더의 <키>.inputs.json (명확성 문구 위치에 쓴다. 없으면 그 지표를 건너뜀)
- 정답 폴더가 없으면 종료 코드 3, scores.json을 쓰지 않는다.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from eval.common.errors import EvalError
from eval.common.goldset import check_goldset_version, gold_path
from eval.common.paths import REPO_ROOT, check_experiment_name, git_commit, is_git_ignored
from eval.common.scores import write_scores
from eval.f1.gold import F1Gold, load_f1_gold
from eval.f3.config import F3EvalConfig, load_config
from eval.f3.pred import F3Pred
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow, load_gold
from eval.retrieval.matchers import CiteMatcher
from eval.retrieval.metrics import random_hit, random_recall
from patent_ai.core.f3_claim_compare.textmatch import find_all_spans
from patent_ai.retrieval.repository import (
    ChunkRepository,
    InMemoryChunkRepository,
    PostgresChunkRepository,
)
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)

METRIC_NAME = "심사관 지정 위치 회수율"
EXIT_NO_GOLD = 3  # 정답 없음 (F4 채점기와 같은 코드)
NO_GOLD = "정답 없음"
# 사람 검수 정답이 있어야 잴 수 있는 지표 (f3-compare-gold.md). 지금은 정답이 없어 재지 않는다
NEEDS_HUMAN_GOLD = (
    "clarity_definition_recall",
    "clarity_issue_type",
    "novelty_difference_recall",
    "novelty_timing",
    "element_judgment_accuracy",
)
FAILURE_KEYS = (
    "missing_prediction",
    "not_searched_rows",
    "excluded_no_location",
    "excluded_clarity",
    "excluded_same_as_other",
    "excluded_body_missing",
    "excluded_gold_not_in_scope",
    "excluded_gold_items_not_in_scope",
    "cq_candidates",
    "novelty_multi_citation",
    "clarity_no_claim_text",
    "clarity_gold_term_not_in_claim",
    "excluded_clarity_no_terms",
    "clarity_location_unreadable",
)
_LOCATION = re.compile(r"\[글자 (\d+)-(\d+)\]")


class GoldMissing(EvalError):
    """정답 폴더·파일이 없다. CLI 종료 코드 3 (scores.json을 쓰지 않는다)."""


@dataclass
class RunInputs:
    """예측 폴더에서 읽은 것. 키는 <출원번호>_<발송번호>."""

    preds: dict[str, F3Pred]
    claims: dict[str, dict[int, str]] = field(default_factory=dict)  # 키 -> OA 당시 청구항 글자


@dataclass
class Report:
    scores: dict
    cq: list[dict]


def _dispatch(key: str) -> str:
    return key.split("_", 1)[1]


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


# ---- ① 심사관 지정 위치 회수율 ----
def _chunk_ids(
    pred: F3Pred, rejection: int, claim: int, doc_id: str
) -> tuple[set[str], set[str], list[int], list[list[int]]]:
    """그 거절이유 × 청구항 × 인용문헌에서 찾은 것.

    돌려주는 값: (검색이 가져온 조각, 모델이 고른 조각, 이 청구항 자기 구성요소 번호,
    부모 청구항에서 온 구성요소 [청구항, 번호]).
    """
    units = {u.unit_id for u in pred.units if u.rejection == rejection}
    searched: set[str] = set()
    elements: set[int] = set()
    parents: set[tuple[int, int]] = set()
    for log in pred.search_log:
        if log.unit_id in units and log.claim == claim and log.doc_id == doc_id:
            searched |= set(log.hit_chunk_ids)
            # 번호는 구성요소가 있는 청구항 안의 순번이라, 부모 것은 청구항을 붙여 따로 둔다.
            # element_claim이 없는 옛 예측은 자기 것으로 본다
            if log.element_claim is None or log.element_claim == claim:
                elements.add(log.element_no)
            else:
                parents.add((log.element_claim, log.element_no))
    selected: set[str] = set()
    for table in pred.comparisons:
        if table.unit_id not in units:
            continue
        for row in table.rows:
            if row.claim != claim:
                continue
            selected |= {e.chunk_id for e in row.evidence if e.document_id == doc_id and e.chunk_id}
    return searched, selected, sorted(elements), [list(p) for p in sorted(parents)]


def _score_cite(
    cfg: F3EvalConfig,
    rows: list[GoldRow],
    preds: dict[str, F3Pred],
    repo: ChunkRepository,
    failures: dict[str, int],
    stamp: dict,
    missing: set[str],
) -> tuple[dict[str, float], set[str], list[dict]]:
    """(지표, 채점한 OA 발송번호, CQ 줄). 줄 점수 -> OA 평균 -> 세트 평균."""
    by_dispatch = {_dispatch(key): pred for key, pred in preds.items()}
    matcher = CiteMatcher()
    per_oa: dict[str, dict[str, list[float]]] = {}
    cq: list[dict] = []
    for row in rows:
        if row.exclude is not None:
            name = f"excluded_{row.exclude}"
            failures[name] = failures.get(name, 0) + 1
            continue
        dispatch, r_part, c_part, doc_id = row.row_id.split(":")
        rejection, claim = int(r_part[1:]), int(c_part[1:])
        scope: list[Chunk] = repo.chunks("cite", cfg.index_version, row.doc_ids, None)
        if not scope:
            failures["excluded_body_missing"] += 1  # 색인에 그 문헌 조각이 없다
            continue
        # 정답 항목마다 맞는 조각 집합. 범위 안에 맞는 조각이 없는 항목은 뺀다 (검색 채점기와 같게)
        matched = [
            {c.chunk_id for c in scope if matcher.matches(c, item, row)} for item in row.items
        ]
        kept = [m for m in matched if m]
        failures["excluded_gold_items_not_in_scope"] += len(matched) - len(kept)
        if not kept:
            failures["excluded_gold_not_in_scope"] += 1
            continue
        marks = per_oa.setdefault(dispatch, {k: [] for k in ("sh", "sr", "lh", "lr", "rr", "rh")})
        pred = by_dispatch.get(dispatch)
        if pred is None:
            missing.add(dispatch)
            searched, selected, elements, parents = set(), set(), [], []
        else:
            searched, selected, elements, parents = _chunk_ids(pred, rejection, claim, doc_id)
            if not elements and not parents:
                failures["not_searched_rows"] += 1  # 그 청구항 × 문헌을 찾은 기록이 없다 (0점)
        found_search = sum(1 for m in kept if m & searched)
        found_selected = sum(1 for m in kept if m & selected)
        marks["sh"].append(float(found_search > 0))
        marks["sr"].append(found_search / len(kept))
        marks["lh"].append(float(found_selected > 0))
        marks["lr"].append(found_selected / len(kept))
        # 무작위 기준선: 같은 범위(N개)에서 검색이 가져온 만큼(k)을 아무렇게나 뽑았을 때의 기대값.
        # 가져온 조각이 0개면 무작위도 0 (함수가 k=0을 막는다)
        if searched:
            n_scope, k_got = len(scope), len(searched)
            marks["rr"].append(random_recall(n_scope, [len(m) for m in kept], k_got))
            marks["rh"].append(random_hit(n_scope, len(set().union(*kept)), k_got))
        else:
            marks["rr"].append(0.0)
            marks["rh"].append(0.0)
        if pred is not None and (elements or parents) and found_search == 0:
            # 못 찾은 질문: 검색을 했는데 정답 위치를 하나도 못 덮음
            # (검색 기록이 없는 줄은 검색을 안 한 것이라 CQ가 아니다. not_searched_rows로만 센다)
            # (질의·정답 위치가 있어 git 밖에만 쓴다)
            cq.append(
                {
                    "row_id": row.row_id,
                    **stamp,
                    "index_version": cfg.index_version,
                    "impl": cfg.impl,
                    "k": cfg.k,
                    "claim": claim,
                    "doc_id": doc_id,
                    "element_nos": elements,
                    "parent_element_nos": parents,
                    "query": row.query,
                    "items": [i.model_dump(mode="json") for i in row.items],
                    "found": sorted(searched),
                    "why": "",
                }
            )
    if failures["excluded_body_missing"]:
        logger.warning(
            "색인(%s)에 조각이 없는 인용문헌의 정답 줄 %d개를 뺐다",
            cfg.index_version,
            failures["excluded_body_missing"],
        )
    if not per_oa:
        # 빼고 남은 줄이 0개면 회수율을 잴 수 없다. 다른 지표만으로 성공하지 않는다
        raise EvalError(
            "검색 정답 줄을 빼고 남은 줄이 0개다 (설정 index_version과 색인 조각을 확인)"
        )
    names = {
        "sh": "search_hit",
        "sr": "search_recall",
        "lh": "selected_hit",
        "lr": "selected_recall",
        "rr": "random_search_recall",
        "rh": "random_search_hit",
    }
    metrics = {
        name: _mean([m for oa in per_oa.values() if (m := _mean(oa[k])) is not None])
        for k, name in names.items()
    }
    metrics = {k: v for k, v in metrics.items() if v is not None}
    # 검색이 무작위보다 몇 배 나은가 (세트 평균끼리 나눔). 분모가 0이면 score_f3가 뺀다
    if metrics.get("random_search_recall"):
        metrics["search_recall_ratio"] = metrics["search_recall"] / metrics["random_search_recall"]
    return metrics, set(per_oa), cq


def _check_not_contaminated(preds: dict[str, F3Pred]) -> None:
    """심사관 지정 줄·위치가 있는 예측은 지정 번호를 입력에 준 실행이다. 회수율이 오염된다."""
    dirty = sum(
        1
        for pred in preds.values()
        if pred.examiner_locations
        or any(r.paragraph_source == "examiner" for t in pred.comparisons for r in t.rows)
    )
    if dirty:
        raise EvalError(
            f"예측 {dirty}건에 심사관 지정 줄이 있다 (지정 번호를 준 실행은 회수율을 잴 수 없음:"
            " use_examiner_paragraphs=false로 다시 돌린다)"
        )


def _check_index_version(preds: dict[str, F3Pred], index_version: str) -> None:
    """예측이 설정과 같은 색인 판으로 만들어졌는지. chunk_id 앞에 판이 붙어 있어,

    판이 다르면 정답 조각과 겹침이 늘 0이 되어 0점이 정상처럼 나온다.
    """
    prefix = f"{index_version}:"
    other = 0
    for pred in preds.values():
        other += sum(
            1 for log in pred.search_log for cid in log.hit_chunk_ids if not cid.startswith(prefix)
        )
        for table in pred.comparisons:
            for row in table.rows:
                other += sum(
                    1
                    for e in row.evidence
                    if e.chunk_id is not None
                    and (e.index_version != index_version or not e.chunk_id.startswith(prefix))
                )
    if other:
        raise EvalError(
            f"예측의 조각 {other}개가 설정의 색인 판 {index_version}이 아니다"
            " (예측을 만든 색인 판과 설정 index_version을 맞춘다)"
        )


# ---- ② 신규성 한 문헌 규칙 ----
def _novelty(preds: dict[str, F3Pred]) -> tuple[int, int]:
    """(신규성 대비표 수, 인용문헌 하나와만 대비하지 않은 표 수)."""
    tables = [t for p in preds.values() for t in p.comparisons if t.rejection_kind == "novelty"]
    bad = sum(
        1
        for t in tables
        if sum(1 for c in t.citations if c.compared) != 1 or len({r.citation for r in t.rows}) > 1
    )
    return len(tables), bad


# ---- ③ 명확성 문구 위치 ----
def _score_clarity(
    golds: list[F1Gold], run: RunInputs, failures: dict[str, int], missing: set[str]
) -> tuple[float | None, set[str]]:
    """(문구 검토 일치율, 채점한 OA 키). 문구 점수 -> OA 평균 -> 세트 평균."""
    per_oa: dict[str, list[float]] = {}
    for g in golds:
        key = f"{g.application_number.value}_{g.dispatch_number.value}"
        rows = [r for r in g.claim_rows if r.clarity_terms]
        kinds = {r.no: r.kind for r in g.rejections}
        # 따옴표 없는 명확성 줄은 문구 위치를 채점하지 않는다 (f3-compare-gold 1절 애매한 경우)
        failures["excluded_clarity_no_terms"] += sum(
            1 for r in g.claim_rows if kinds.get(r.rejection) == "clarity" and not r.clarity_terms
        )
        if not rows:
            continue
        pred = run.preds.get(key)
        claims = run.claims.get(key)
        if pred is not None and claims is None:
            failures["clarity_no_claim_text"] += 1  # 청구항 글자가 없어 정답 자리를 정할 수 없다
            continue
        marks = per_oa.setdefault(key, [])
        if pred is None:
            missing.add(g.dispatch_number.value)
        for row in rows:
            for term in row.clarity_terms:
                if pred is None:
                    marks.append(0.0)
                    continue
                gold_spans = find_all_spans(term, claims.get(row.claim, ""))
                if not gold_spans:
                    failures["clarity_gold_term_not_in_claim"] += 1  # 정답 표현이 청구항에 없다
                    continue
                ok = False
                for review in pred.clarity_reviews:
                    m = _LOCATION.search(review.claim_location)
                    same = " ".join(review.term.split()) == " ".join(term.split())
                    if review.claim != row.claim or not same:
                        continue
                    if m is None:
                        # 위치 꼴(`[글자 a-b]`)을 못 읽음: 앱이 위치를 못 정했거나 꼴이 바뀜 (틀림)
                        failures["clarity_location_unreadable"] += 1
                        continue
                    a, b = int(m.group(1)), int(m.group(2))
                    # 같은 표현이 여러 번 나오면 하나라도 겹치면 맞음
                    ok = ok or any(a < end and start < b for start, end in gold_spans)
                marks.append(float(ok))
    scored = {k: v for k, v in per_oa.items() if v}
    return _mean([sum(v) / len(v) for v in scored.values()]), set(scored)


def score_f3(
    cfg: F3EvalConfig,
    cite_rows: list[GoldRow] | None,
    f1_golds: list[F1Gold] | None,
    run: RunInputs,
    repo: ChunkRepository,
    *,
    commit: str,
    gold_sha256: str,
) -> Report:
    """정답(없는 쪽은 None)과 예측을 맞춰 scores와 CQ 줄을 만든다. 파일은 쓰지 않는다."""
    started = time.monotonic()
    if not run.preds:
        raise EvalError("F3 예측이 0개다")
    _check_not_contaminated(run.preds)
    _check_index_version(run.preds, cfg.index_version)
    failures = dict.fromkeys(FAILURE_KEYS, 0)
    metrics: dict[str, float] = {}
    skipped = dict.fromkeys(NEEDS_HUMAN_GOLD, NO_GOLD)
    stamp = {"goldset_version": cfg.goldset_version, "gold_sha256": gold_sha256}
    scored: set[str] = set()
    cq: list[dict] = []
    missing: set[str] = set()  # 정답은 있는데 예측이 없는 OA (발송번호). 0점으로 센다

    if cite_rows is None:
        for name in (
            "search_hit",
            "search_recall",
            "selected_hit",
            "selected_recall",
            "random_search_recall",
            "random_search_hit",
            "search_recall_ratio",
        ):
            skipped[name] = NO_GOLD
    else:
        cite_metrics, oas, cq = _score_cite(
            cfg, cite_rows, run.preds, repo, failures, stamp, missing
        )
        metrics.update(cite_metrics)
        if "search_recall_ratio" not in cite_metrics:
            skipped["search_recall_ratio"] = "무작위 기준선이 0이라 나눌 수 없음"
        scored |= oas
        failures["cq_candidates"] = len(cq)

    tables, bad = _novelty(run.preds)
    metrics["novelty_tables"] = tables
    failures["novelty_multi_citation"] = bad
    if bad:
        logger.warning("신규성 대비표 %d개가 인용문헌 하나와만 대비하지 않았다", bad)

    if f1_golds is None:
        skipped["clarity_term_reviewed"] = NO_GOLD
    else:
        accuracy, oas = _score_clarity(f1_golds, run, failures, missing)
        if accuracy is None:
            why = (
                "청구항 글자 입력 없음" if failures["clarity_no_claim_text"] else "채점할 문구 없음"
            )
            skipped["clarity_term_reviewed"] = why
        else:
            metrics["clarity_term_reviewed"] = accuracy
            scored |= {_dispatch(k) for k in oas}

    failures["missing_prediction"] = len(missing)
    if missing:
        logger.warning("F3 예측이 없는 OA %d건 (0점으로 셈)", len(missing))
    by_dispatch = {_dispatch(k) for k in run.preds}
    if not scored & by_dispatch:
        # 전부 빠졌으면 0점으로 성공하지 않는다 (조용한 실패 금지)
        raise EvalError(
            "F3 예측이 하나도 정답 OA와 맞지 않는다 (이름: <출원번호>_<발송번호>.f3.json)"
        )
    scores = {
        "experiment": cfg.experiment,
        "commit": commit,
        "goldset": cfg.goldset,
        "goldset_version": cfg.goldset_version,
        "gold_sha256": gold_sha256,
        "impl": cfg.impl,
        "index_version": cfg.index_version,
        "metric_name": METRIC_NAME,
        "n": len(scored),  # 채점한 OA 수
        "metrics": metrics,
        "failures": failures,
        "skipped_metrics": skipped,  # 재지 않은 지표와 이유 (0점이 아니다)
        "cost": {  # 채점은 모델을 부르지 않는다
            "usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "external_calls": 0,
            "seconds": round(time.monotonic() - started, 3),
        },
    }
    return Report(scores, cq)


# ---- 명령 (파일 읽기·쓰기) ----
def load_run(folder: Path) -> RunInputs:
    """예측 폴더의 <키>.f3.json과 (있으면) <키>.inputs.json을 읽는다. 틀린 파일은 순번만 말한다."""
    if not folder.is_dir():
        raise EvalError("F3 예측 폴더가 없다")
    run = RunInputs(preds={})
    for i, f in enumerate(sorted(folder.glob("*.f3.json")), start=1):
        key = f.name.removesuffix(".f3.json")
        try:
            run.preds[key] = F3Pred.model_validate_json(f.read_text(encoding="utf-8"))
        except ValidationError:
            # 파일 이름(출원번호)과 원문 글자는 메시지에 넣지 않는다
            raise EvalError(f"예측 파일 {i}번째: F3Result 모양이 아니다") from None
        inputs = folder / f"{key}.inputs.json"
        if inputs.is_file():
            try:
                claims = json.loads(inputs.read_text(encoding="utf-8"))["claims_at_oa"]
                run.claims[key] = {int(n): text for n, text in claims.items()}
            except json.JSONDecodeError, KeyError, ValueError, AttributeError:
                raise EvalError(f"입력 파일 {i}번째: claims_at_oa를 읽을 수 없다") from None
    return run


def _load_golds(
    cfg: F3EvalConfig, root: Path
) -> tuple[list[GoldRow] | None, list[F1Gold] | None, str]:
    """(검색 정답, F1 정답, 해시). 없는 쪽은 None. 둘 다 없으면 GoldMissing."""
    cite_path = gold_path(root, cfg.goldset, cfg.cite_gold)
    f1_dir = gold_path(root, cfg.goldset, cfg.f1_gold)
    has_cite = cite_path.is_file()
    has_f1 = f1_dir.is_dir() and any(f1_dir.glob("*.json"))
    if not has_cite and not has_f1:
        raise GoldMissing("F3 정답(검색 정답 파일, F1 정답 폴더)이 하나도 없다")
    check_goldset_version(root, cfg.goldset_version)
    h = hashlib.sha256()
    cite_rows = f1_golds = None
    if has_cite:
        try:
            cite_rows = [r for r in load_gold(cite_path) if r.corpus == "cite"]
        except RetrievalEvalError as e:
            raise EvalError(str(e)) from None
        h.update(cite_path.read_bytes())
    else:
        logger.warning("검색 정답 파일이 없어 회수율을 재지 않는다 (%s)", NO_GOLD)
    if has_f1:
        f1_golds = load_f1_gold(f1_dir, expected_version=cfg.goldset_version)
        for f in sorted(f1_dir.glob("*.json")):
            h.update(f.read_bytes())
    else:
        logger.warning("F1 정답 폴더가 없어 명확성 문구 위치를 재지 않는다 (%s)", NO_GOLD)
    return cite_rows, f1_golds, h.hexdigest()


def write_cq(lines: list[dict], path: Path) -> int:
    """못 찾은 질문을 한 줄씩 jsonl로 쓴다 (질의·정답 위치가 있어 git 밖에만). 0건이면 경고."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), "utf-8")
    if not lines:
        logger.warning("CQ 후보가 0건이다 (못 찾은 질문이 없거나 채점한 줄이 없음)")
    return len(lines)


def postgres_repo() -> ChunkRepository:
    """진짜 색인 DB 저장소 (DATABASE_URL). 테스트는 --chunks를 쓴다."""
    return PostgresChunkRepository.from_url()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.f3.score")
    ap.add_argument("--config", required=True)
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--predictions", required=True, help="F3Result JSON 폴더 (git 밖)")
    ap.add_argument("--chunks", default=None, help="조각 JSONL. 없으면 Postgres(DATABASE_URL)")
    ap.add_argument("--scores-dir", default=None)
    ap.add_argument("--cq-dir", default=None, help="기본 work/f3/<실험>/ (git 밖)")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        check_experiment_name(cfg.experiment)
        pred_dir = Path(args.predictions)
        # 예측에는 청구항·인용문헌 글자가 있어 git에 들어갈 수 있는 경로면 멈춘다
        if not is_git_ignored(pred_dir):
            raise EvalError(
                "예측 폴더가 git에 들어갈 수 있는 경로다 (저장소 밖이나 무시되는 경로만)"
            )
        root = Path(args.goldsets_root)
        cite_rows, f1_golds, sha = _load_golds(cfg, root)
        run = load_run(pred_dir)
        chunks_mode = args.chunks is not None
        repo = (
            InMemoryChunkRepository.from_jsonl("cite", args.chunks)
            if chunks_mode
            else postgres_repo()
        )
        report = score_f3(cfg, cite_rows, f1_golds, run, repo, commit=git_commit(), gold_sha256=sha)
        work_dir = REPO_ROOT / "work" / "f3" / cfg.experiment
        cq_dir = Path(args.cq_dir) if args.cq_dir else work_dir
        if not is_git_ignored(cq_dir):
            raise EvalError("CQ 폴더가 git에 들어갈 수 있는 경로다 (질의·정답 위치가 들어간다)")
        report.scores["failures"]["cq_candidates"] = write_cq(
            report.cq, cq_dir / "cq_candidates.jsonl"
        )
        # 가짜 조각(--chunks)으로 돌린 점수가 experiments/ 점수 표에 섞이지 않게 work/ 아래에 쓴다
        default_dir = work_dir if chunks_mode else REPO_ROOT / "experiments" / cfg.experiment
        write_scores(Path(args.scores_dir) if args.scores_dir else default_dir, report.scores)
    except GoldMissing as e:
        print(f"{NO_GOLD}: {e} (scores.json을 쓰지 않음)", file=sys.stderr)
        return EXIT_NO_GOLD
    except EvalError as e:
        print(f"채점 실패: {e}", file=sys.stderr)
        return 1
    skipped = report.scores["skipped_metrics"]
    print(f"scores.json 저장: n={report.scores['n']}", file=sys.stderr)
    print(
        f"재지 않은 지표 {len(skipped)}개 ({NO_GOLD} 등): {', '.join(sorted(skipped))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
