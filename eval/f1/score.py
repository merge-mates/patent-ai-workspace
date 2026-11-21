"""F1 채점 (이슈 #20 task 3·5). 정답 꼴 예측 대 정답 꼴 정답.

점수 단위는 칸 하나 = 맞음/틀림 하나 (기본 8, 거절이유마다 4, 인용마다 2, 청구항 줄마다 3~4).
OA 한 통마다 정확도를 내고 그 평균이 주 점수다. score_f1은 파일을 쓰지 않는다 (쓰기는 main).
scores에는 출원번호·발송번호·원문 글자를 넣지 않는다 (건수와 비율만).

명령: uv run python eval/run_eval.py --config <설정> --predictions <폴더>
      [--pages <폴더>] [--calls <호출 기록 JSON>]
- 예측: <폴더>/<출원번호>_<발송번호>.json (read_oa가 낸 OAResult JSON)
- 쪽 글자: <폴더>/<출원번호>_<발송번호>.pages.json (extract_pages가 낸 PageText JSON)
- 호출 기록: JSON 리스트, 한 줄 = core/llm/limits.py CallRecord를 dict로
  (선택 키 case = 사건 이름표). input_tokens·output_tokens·cost·from_cache·outcome만 읽고
  stop_reason 같은 다른 키는 무시한다.
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from eval.common.errors import EvalError
from eval.common.goldset import check_goldset_version, gold_path
from eval.common.paths import REPO_ROOT, check_experiment_name, git_commit, is_git_ignored
from eval.common.scores import write_scores
from eval.f1.adapt import to_pred
from eval.f1.config import F1EvalConfig, load_config
from eval.f1.gold import F1Gold, load_f1_gold
from eval.f1.metrics import (
    cite_key,
    clarity_match,
    location_pairs,
    page_in,
    same_as_match,
    text_eq,
)
from eval.f1.on_page import text_on_page
from eval.f1.pred import F1Pred
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)

METRIC_NAME = "필드별 추출 정확도"
GROUPS = ("basic", "rejections", "citations", "claim_rows")
FAILURE_KEYS = (
    "missing_prediction",
    "pages_missing",
    "excluded_location_same_as",
    "excluded_location_none",
)


def oa_key(g: F1Gold) -> str:
    """OA 하나를 가리키는 키 (출원번호 + 발송번호). 예측·쪽 글자 묶음의 키로 쓴다."""
    return f"{g.application_number.value}_{g.dispatch_number.value}"


@dataclass
class OAScore:
    """OA 한 통의 채점 결과. scores에는 합친 값만 싣는다."""

    correct: dict[str, int] = field(default_factory=lambda: dict.fromkeys(GROUPS, 0))
    total: dict[str, int] = field(default_factory=lambda: dict.fromkeys(GROUPS, 0))
    fabricated: int = 0
    loc_recalls: list[float] = field(default_factory=list)  # 위치 채점 줄마다
    loc_exacts: list[bool] = field(default_factory=list)
    excluded_same_as: int = 0
    excluded_none: int = 0

    def add(self, group: str, ok: bool) -> None:
        self.total[group] += 1
        self.correct[group] += int(ok)

    @property
    def accuracy(self) -> float:
        t = sum(self.total.values())
        return sum(self.correct.values()) / t if t else 0.0


def _extra(pred: list[int] | None, gold: list[int]) -> int:
    """정답에 없는 번호를 더 낸 개수 (지어낸 값)."""
    return len(set(pred or []) - set(gold))


def _score_basic(g: F1Gold, p: F1Pred, s: OAScore) -> None:
    s.add("basic", p.application_number.value == g.application_number.value)
    s.add("basic", p.dispatch_number.value == g.dispatch_number.value)
    s.add("basic", text_eq(p.notice_date.text, g.notice_date.text))
    s.add("basic", text_eq(p.response_due.text, g.response_due.text))
    s.add("basic", p.notice_kind.value == g.notice_kind.value)
    for gc, pc in (
        (g.examined_claims, p.examined_claims),
        (g.allowable_claims, p.allowable_claims),
    ):
        s.add("basic", pc.value is not None and set(pc.value) == set(gc.value))
    # 안 낸 칸(given=False)은 정답이 '없음'(None)이어도 틀림
    s.add(
        "basic",
        p.amendment_note.given and text_eq(p.amendment_note.value, g.amendment_note.value),
    )

    # 지어낸 값: 정답이 '없음'인데 값을 냄 (특허 가능한 청구항·보정 참고사항)
    if not g.allowable_claims.value:
        s.fabricated += int(bool(p.allowable_claims.value))
    else:
        s.fabricated += _extra(p.allowable_claims.value, g.allowable_claims.value)
    if g.amendment_note.value is None and p.amendment_note.value is not None:
        s.fabricated += 1
    s.fabricated += _extra(p.examined_claims.value, g.examined_claims.value)


def _score_rejections(g: F1Gold, p: F1Pred, s: OAScore) -> None:
    # 칸 4개: 종류·조문·지원·대상. 종류와 지원은 같은 조문 규칙에서 나와 틀리면 둘이 같이 틀린다
    pred_by_no = {r.no: r for r in p.rejections}
    for gr in g.rejections:
        pr = pred_by_no.get(gr.no)
        if pr is None:
            for _ in range(4):
                s.add("rejections", False)
            continue
        s.add("rejections", pr.kind == gr.kind)
        s.add("rejections", pr.article is not None and text_eq(pr.article, gr.article))
        s.add("rejections", pr.supported == gr.supported)
        s.add(
            "rejections",
            pr.targets.value is not None and set(pr.targets.value) == set(gr.targets.value),
        )
        s.fabricated += _extra(pr.targets.value, gr.targets.value)
    gold_nos = {r.no for r in g.rejections}
    # 정답에 없는 거절이유는 확인된 칸이 하나라도 있을 때만 지어낸 값
    # (전부 확인되지 않음이면 앱이 안 낸 것)
    s.fabricated += sum(
        1
        for r in p.rejections
        if r.no not in gold_nos
        and (r.kind is not None or r.article is not None or r.targets.value is not None)
    )


def _score_citations(g: F1Gold, p: F1Pred, s: OAScore) -> None:
    pred_by_label = {c.label: c for c in p.citations}
    for gc in g.citations:
        pc = pred_by_label.get(gc.label)
        if pc is None:
            s.add("citations", False)
            s.add("citations", False)
            continue
        s.add("citations", pc.key is not None and cite_key(pc.key) == cite_key(gc.key))
        s.add("citations", set(pc.rejections) == set(gc.rejections))
    gold_labels = {c.label for c in g.citations}
    # 정답에 없는 인용은 번호(key)가 확인됐을 때만 지어낸 값
    s.fabricated += sum(1 for c in p.citations if c.label not in gold_labels and c.key is not None)


def _score_claim_rows(g: F1Gold, p: F1Pred, s: OAScore) -> None:
    kind_by_no = {r.no: r.kind for r in g.rejections}
    pred_rows = {(r.claim, r.rejection): r for r in p.claim_rows}
    for gr in g.claim_rows:
        pr = pred_rows.get((gr.claim, gr.rejection))
        clarity = kind_by_no[gr.rejection] == "clarity"
        # 이 줄의 칸: 있음, (명확성이면 표현 / 아니면 인용), (같은 취지가 있으면) 같은 취지, 쪽
        s.add("claim_rows", pr is not None)
        if clarity:
            s.add(
                "claim_rows", pr is not None and clarity_match(gr.clarity_terms, pr.clarity_terms)
            )
        else:
            s.add("claim_rows", pr is not None and set(pr.citations) == set(gr.citations))
        if gr.same_as:
            s.add("claim_rows", pr is not None and same_as_match(gr.same_as, pr.same_as))
        s.add("claim_rows", pr is not None and page_in(gr.page, gr.page_end, pr.page))

        # 짚은 위치 (명확성 줄은 위치가 없다)
        if clarity:
            continue
        gold_pairs = location_pairs(gr.locations)
        if not gold_pairs:
            # 같은 취지만 가리키는 줄, 위치 없음만 있는 줄은 위치 채점에서 뺀다 (3절 1·4번)
            if gr.same_as:
                s.excluded_same_as += 1
            else:
                s.excluded_none += 1
            continue
        pred_pairs = location_pairs(pr.locations) if pr is not None else set()
        s.loc_recalls.append(len(gold_pairs & pred_pairs) / len(gold_pairs))
        s.loc_exacts.append(gold_pairs == pred_pairs)
        s.fabricated += len(pred_pairs - gold_pairs)

    gold_keys = {(r.claim, r.rejection) for r in g.claim_rows}
    s.fabricated += sum(1 for k in pred_rows if k not in gold_keys)


def _score_oa(g: F1Gold, p: F1Pred) -> OAScore:
    s = OAScore()
    _score_basic(g, p, s)
    _score_rejections(g, p, s)
    _score_citations(g, p, s)
    _score_claim_rows(g, p, s)
    return s


def _missing_oa(g: F1Gold) -> OAScore:
    """예측이 없는 OA: 칸은 다 틀림(0점), 위치 줄은 재현율 0 (빼지 않는다).

    빈 예측으로 채점하면 '없음 = 없음'이 우연히 맞음이 되므로, 칸 수만 세고 맞음은 0으로 둔다.
    """
    s = _score_oa(g, F1Pred())
    s.correct = dict.fromkeys(GROUPS, 0)
    s.fabricated = 0
    s.loc_exacts = [False] * len(s.loc_exacts)
    s.loc_recalls = [0.0] * len(s.loc_recalls)
    return s


def count_unverified(p: F1Pred, pages: PageText) -> int:
    """원문 글자를 낸 값 중 붙은 쪽 글자에 없는 것의 수 (requirements 9번).

    대조 규칙은 on_page.py (앱 원문 대조와 같음).
    """
    checks: list[tuple[str, int | None]] = []
    for v in (
        p.application_number,
        p.dispatch_number,
        p.notice_date,
        p.response_due,
        p.notice_kind,
        p.examined_claims,
        p.allowable_claims,
        p.amendment_note,
    ):
        if v.text:
            checks.append((v.text, v.page))
    for r in p.rejections:
        for t in (r.article, r.targets.text):
            if t:
                checks.append((t, r.page))
    for c in p.citations:
        if c.text:
            checks.append((c.text, c.page))
    for row in p.claim_rows:
        if row.text:
            checks.append((row.text, row.page))  # 두 쪽에 걸치면 시작 쪽 (앱과 같음)
    return sum(1 for text, page in checks if not text_on_page(pages, page, text))


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


RESPONDED_OUTCOMES = ("ok", "invalid_output", "output_truncated")  # 응답을 받은 결과


def _sum_known(calls: list[dict], key: str) -> int | None:
    """토큰 칸 합. 확인되지 않은(None) 줄이 하나라도 있으면 일부만 더한 합 대신 None."""
    vals = [c[key] for c in calls]
    return None if any(v is None for v in vals) else sum(vals)


def sum_calls(calls: list[dict] | None, n_oa: int | None = None) -> dict:
    """read_oa 실행 호출 기록을 cost 칸으로 합친다. 모르는 키는 안 본다.

    호출 수·토큰·usd는 모두 실제로 외부에 부른 호출만 센다 (한 칸 안에서 기준을 맞춘다).
    캐시 적중 토큰은 과금이 없으니 cached_input_tokens·cached_output_tokens에 따로 둔다.
    n_oa(채점한 OA 수)를 주면 기록의 사건(case) 수가 그보다 적을 때 경고한다.
    """
    zero = {
        "usd": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "cached_output_tokens": 0,
        "external_calls": 0,
    }
    if calls is None:
        logger.warning("실행 호출 기록(--calls)이 없어 cost에 채점기 비용만 씀")
        return zero
    if not calls:
        logger.warning("실행 호출 기록이 0줄 (cost를 0으로 씀)")
        return zero
    # 파일을 두 번 이어 붙이면 똑같은 줄이 생긴다 (재시도는 attempt·transport_try가 달라 안 걸림)
    seen = [json.dumps(c, sort_keys=True, ensure_ascii=False) for c in calls]
    dup = len(seen) - len(set(seen))
    if dup:
        logger.warning("호출 기록에 똑같이 겹친 줄 %d개 (파일을 두 번 합쳤는지 확인)", dup)
    # 일부 사건만 담긴 기록이면 비용이 덜 잡힌다. case 이름은 예측 키와 꼴이 달라 수만 본다
    cases = {c["case"] for c in calls if "case" in c}
    if cases and n_oa is not None and len(cases) < n_oa:
        logger.warning(
            "호출 기록의 사건 %d개가 채점한 OA %d건보다 적다 (비용이 덜 잡혔을 수 있음)",
            len(cases),
            n_oa,
        )
    # 실제로 외부에 부른 기록: 캐시 적중과, 전송층 앞에서 막힌 limit_exceeded는 뺀다
    real = [c for c in calls if not c["from_cache"] and c["outcome"] != "limit_exceeded"]
    cached = [c for c in calls if c["from_cache"]]
    # 토큰이 None = 스트림이 끊겨 청구량을 모르는 호출 (#194). 합이 틀릴 수 있어 usd를 비운다
    unknown = [c for c in real if c["input_tokens"] is None or c["output_tokens"] is None]
    known = [c for c in real if c not in unknown]
    # 응답을 받았는데 가격이 비어 있으면 합이 틀리므로 usd를 비운다 (응답 없는 줄의 None은 0)
    unpriced = sum(
        1
        for c in known
        if c["cost"] is None
        and (c["input_tokens"] > 0 or c["output_tokens"] > 0 or c["outcome"] in RESPONDED_OUTCOMES)
    )
    usd: float | None = sum(c["cost"] or 0.0 for c in real)
    if unpriced:
        logger.warning("가격 설정이 없어 usd를 비움 (가격 없는 호출 기록 %d줄)", unpriced)
        usd = None
    if unknown:
        logger.warning(
            "토큰이 확인되지 않은 호출 기록 %d줄이 있어 usd와 그 토큰 칸의 합을 비움",
            len(unknown),
        )
        usd = None
    return {
        "usd": usd,
        "input_tokens": _sum_known(real, "input_tokens"),
        "output_tokens": _sum_known(real, "output_tokens"),
        "cached_input_tokens": _sum_known(cached, "input_tokens"),
        "cached_output_tokens": _sum_known(cached, "output_tokens"),
        "external_calls": len(real),
    }


def score_f1(
    cfg: F1EvalConfig,
    golds: list[F1Gold],
    preds: dict[str, F1Pred],
    pages: dict[str, PageText] | None,
    *,
    commit: str,
    gold_sha256: str,
    calls: list[dict] | None = None,
) -> dict:
    """정답 OA마다 예측과 맞춰 scores dict를 만든다. preds·pages의 키는 oa_key(정답)."""
    started = time.monotonic()
    if not golds:
        raise EvalError("F1 정답이 0개다")
    if not any(oa_key(g) in preds for g in golds):
        # 전부 빠졌으면 0점으로 성공하지 않는다 (조용한 실패 금지)
        raise EvalError("F1 예측이 하나도 정답 OA와 맞지 않는다")

    failures = dict.fromkeys(FAILURE_KEYS, 0)
    per_oa: list[OAScore] = []
    unverified = 0
    for g in golds:
        key = oa_key(g)
        p = preds.get(key)
        if p is None:
            failures["missing_prediction"] += 1
            per_oa.append(_missing_oa(g))
            continue
        per_oa.append(_score_oa(g, p))
        if pages is None or key not in pages:
            failures["pages_missing"] += 1
        else:
            unverified += count_unverified(p, pages[key])
    if failures["missing_prediction"]:
        logger.warning("F1 예측이 없는 OA %d건 (0점으로 셈)", failures["missing_prediction"])

    correct = {grp: sum(s.correct[grp] for s in per_oa) for grp in GROUPS}
    total = {grp: sum(s.total[grp] for s in per_oa) for grp in GROUPS}
    metrics: dict[str, float] = {
        "field_accuracy": sum(s.accuracy for s in per_oa) / len(per_oa),
        "field_accuracy_micro": sum(correct.values()) / sum(total.values()),
    }
    for grp in GROUPS:
        if total[grp]:
            metrics[f"field_accuracy.{grp}"] = correct[grp] / total[grp]
    # 위치: OA마다 줄 평균 -> 위치 줄이 있는 OA끼리 평균 (OA 한 통이 한 표)
    loc_recall = _mean([m for s in per_oa if (m := _mean(s.loc_recalls)) is not None])
    loc_exact = _mean(
        [m for s in per_oa if (m := _mean([float(x) for x in s.loc_exacts])) is not None]
    )
    if loc_recall is None:
        logger.warning("F1 위치 채점 줄이 0개 (location 지표를 뺌)")
    else:
        metrics["location_recall"] = loc_recall
        metrics["location_exact"] = loc_exact
    metrics["fabricated_values"] = sum(s.fabricated for s in per_oa)
    # 쪽 글자가 하나라도 빠지면 지표를 빼고 건수만 (0으로 쓰지 않는다, #20 Q5)
    if failures["pages_missing"]:
        logger.warning(
            "F1 쪽 글자가 없는 OA %d건 (unverified_locations를 뺌)", failures["pages_missing"]
        )
    else:
        metrics["unverified_locations"] = unverified
    failures["excluded_location_same_as"] = sum(s.excluded_same_as for s in per_oa)
    failures["excluded_location_none"] = sum(s.excluded_none for s in per_oa)

    return {
        "experiment": cfg.experiment,
        "commit": commit,
        "goldset": cfg.goldset,
        "goldset_version": cfg.goldset_version,
        "gold_sha256": gold_sha256,
        "impl": cfg.impl,
        "metric_name": METRIC_NAME,
        "n": len(golds),
        "metrics": metrics,
        "failures": failures,
        # 채점은 모델을 부르지 않는다. 읽기 비용은 예측을 만든 실행의 호출 기록(--calls)에서 온다.
        # seconds는 채점기 시간만 (실행 시간은 합치지 않는다)
        "cost": {**sum_calls(calls, len(golds)), "seconds": round(time.monotonic() - started, 3)},
    }


# ---- 명령 (파일 읽기·쓰기)


def _gold_sha256(folder: Path) -> str:
    """정답 파일들을 이름 순서로 이어 붙인 해시 (정답이 바뀌었는지 scores에 남긴다)."""
    h = hashlib.sha256()
    for f in sorted(folder.glob("*.json")):
        h.update(f.read_bytes())
    return h.hexdigest()


def default_scores_dir(goldsets_root: Path, experiment: str) -> Path:
    """진짜 정답 폴더(…/data/goldsets)면 experiments/<실험>/, 아니면 work/f1/<실험>/.

    가짜 정답으로 돌린 점수가 experiments/에 남아 점수 표에 섞이지 않게 한다.
    """
    if Path(goldsets_root).resolve().parts[-2:] == ("data", "goldsets"):
        return REPO_ROOT / "experiments" / experiment
    return REPO_ROOT / "work" / "f1" / experiment


def load_predictions(folder: Path) -> dict[str, F1Pred]:
    """예측 폴더의 <키>.json(OAResult)을 읽어 정답 꼴로 바꾼다. 틀린 파일은 순번만 말하고 멈춘다."""
    if not folder.is_dir():
        raise EvalError("F1 예측 폴더가 없다")
    files = sorted(f for f in folder.glob("*.json") if not f.name.endswith(".pages.json"))
    preds: dict[str, F1Pred] = {}
    for i, f in enumerate(files, start=1):
        try:
            oa = OAResult.model_validate_json(f.read_text(encoding="utf-8"))
        except ValidationError:
            # 파일 이름(출원번호)과 원문 글자는 메시지에 넣지 않는다
            raise EvalError(f"예측 파일 {i}번째: OAResult 모양이 아니다") from None
        try:
            preds[f.stem] = to_pred(oa)
        except ValidationError:
            # OAResult는 맞는데 정답 꼴로 못 바꿈 (예: 라벨 꼴). 값 글자는 메시지에 넣지 않는다
            raise EvalError(f"예측 파일 {i}번째: 정답 꼴로 바꿀 수 없다 (라벨·번호 꼴)") from None
    return preds


def load_pages(folder: Path) -> dict[str, PageText]:
    # 쪽 글자를 주었는데 못 읽으면 오타일 수 있어 멈춘다 (안 준 것은 지표를 빼고 계속, #20 Q5)
    if not folder.is_dir():
        raise EvalError("쪽 글자 폴더가 없다")
    pages: dict[str, PageText] = {}
    for i, f in enumerate(sorted(folder.glob("*.pages.json")), start=1):
        try:
            pt = PageText.model_validate_json(f.read_text(encoding="utf-8"))
        except ValidationError:
            raise EvalError(f"쪽 글자 파일 {i}번째: PageText 모양이 아니다") from None
        pages[f.name.removesuffix(".pages.json")] = pt
    return pages


def load_calls(path: Path) -> list[dict]:
    """호출 기록 JSON(리스트)을 읽는다. 틀리면 파일 이름과 줄 순번만 말하고 멈춘다."""
    name = path.name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        raise EvalError(f"호출 기록 파일({name})을 읽을 수 없다 (없거나 JSON이 아님)") from None
    if not isinstance(data, list):
        raise EvalError(f"호출 기록 파일({name})이 리스트가 아니다")
    # 필요한 키만 본다. stop_reason·case 같은 모르는 키는 무시
    types: dict[str, tuple[type, ...]] = {
        # None = 확인되지 않음 (스트림이 끊긴 호출, #194)
        "input_tokens": (int, type(None)),
        "output_tokens": (int, type(None)),
        "cost": (int, float, type(None)),
        "from_cache": (bool,),
        "outcome": (str,),
    }
    for i, c in enumerate(data, start=1):
        if not isinstance(c, dict):
            raise EvalError(f"호출 기록 파일({name}) {i}번째 줄이 객체가 아니다")
        for key, ok_types in types.items():
            v = c.get(key, KeyError)  # 키가 없는 것과 None을 가른다
            # bool은 int의 하위 타입이라 토큰·비용 칸에서는 따로 막는다
            if (
                v is KeyError
                or not isinstance(v, ok_types)
                or (isinstance(v, bool) and bool not in ok_types)
            ):
                raise EvalError(
                    f"호출 기록 파일({name}) {i}번째 줄의 {key} 칸이 없거나 타입이 틀리다"
                )
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.f1.score")
    ap.add_argument("--config", required=True)
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--predictions", required=True, help="read_oa 결과 OAResult JSON 폴더 (git 밖)")
    ap.add_argument("--pages", default=None, help="extract_pages 결과 PageText JSON 폴더 (git 밖)")
    ap.add_argument(
        "--scores-dir",
        default=None,
        help="기본: 진짜 정답이면 experiments/<실험>/, 아니면 work/f1/<실험>/",
    )
    ap.add_argument(
        "--calls",
        default=None,
        help="read_oa 실행 호출 기록 JSON 파일 (git 밖). 없으면 cost는 채점기 비용만",
    )
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        check_experiment_name(cfg.experiment)
        pred_dir = Path(args.predictions)
        pages_dir = Path(args.pages) if args.pages else None
        calls_path = Path(args.calls) if args.calls else None
        # 예측·쪽 글자에는 OA 원문 글자, 호출 기록에는 사건 이름(case)이 있어
        # git에 들어갈 수 있는 경로면 멈춘다
        for d in (pred_dir, pages_dir, calls_path):
            if d is not None and not is_git_ignored(d):
                msg = "예측·쪽 글자 폴더·호출 기록이 git에 들어갈 수 있는 경로다"
                raise EvalError(msg + " (저장소 밖이나 무시되는 경로만)")
        calls = load_calls(calls_path) if calls_path is not None else None
        root = Path(args.goldsets_root)
        check_goldset_version(root, cfg.goldset_version)
        folder = gold_path(root, cfg.goldset, cfg.gold)
        golds = load_f1_gold(folder, expected_version=cfg.goldset_version)
        preds = load_predictions(pred_dir)
        extra = set(preds) - {oa_key(g) for g in golds}
        if extra:
            logger.warning("정답에 없는 예측 %d건 (채점에서 뺌)", len(extra))
        pages = load_pages(pages_dir) if pages_dir is not None else None
        if pages is not None and not set(pages) & {oa_key(g) for g in golds}:
            raise EvalError(
                "쪽 글자 파일이 정답 OA와 하나도 맞지 않는다"
                " (이름: <출원번호>_<발송번호>.pages.json)"
            )
        scores = score_f1(
            cfg,
            golds,
            preds,
            pages,
            commit=git_commit(),
            gold_sha256=_gold_sha256(folder),
            calls=calls,
        )
        scores_dir = (
            Path(args.scores_dir) if args.scores_dir else default_scores_dir(root, cfg.experiment)
        )
        write_scores(scores_dir, scores)
    except EvalError as e:
        print(f"채점 실패: {e}", file=sys.stderr)
        return 1
    print(f"scores.json 저장: n={scores['n']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
