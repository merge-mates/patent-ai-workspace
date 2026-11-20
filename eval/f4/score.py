"""F4 대응 방향 채점 (①②층). 규칙은 docs/evaluation/f4-direction-gold.md 2·3·5절.

채점 단위는 정답 한 줄 = OA 시점 청구항 × 거절이유. 청구항 점수 -> OA 평균 -> 세트 평균.
- ① 다뤘나: 정답 `handled`와, AI가 그 (거절이유, 청구항)을 묶음에 두고 그 묶음 결과
  (후보나 직접 판단 필요)를 냈는지가 같은가
- ② 거친 방향 1등 일치율: 1등 후보의 청구항별 보정 종류에서 계산한 방향이 정답과 같은가
- 누락: 정답 줄 가운데 AI의 어느 묶음에도 없는 (거절이유, 청구항) 쌍 수 (failures)
③④층, 실제 방향의 순위, 확신도 단계별·독립항만 점수는 아직 내지 않는다.
scores에는 출원번호·발송번호·원문 글자를 넣지 않는다 (건수와 비율만).

명령: uv run python eval/run_eval.py --config <설정> --predictions <폴더>
정답 폴더가 없으면 점수를 쓰지 않고 "정답 없음"으로 끝낸다 (종료 코드 EXIT_NO_GOLD).
direction_top1은 보류(직접 판단 필요) 줄을 뺀 값이다. 보류가 늘면 오를 수 있으므로
needs_human_judgment_rate·direction_top1_strict와 같이 본다.
"""

import argparse
import hashlib
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from eval.common.errors import EvalError
from eval.common.goldset import check_goldset_version, gold_path
from eval.common.paths import REPO_ROOT, check_experiment_name, git_commit, is_git_ignored
from eval.common.scores import write_scores
from eval.f4.config import F4EvalConfig, load_config
from eval.f4.gold import F4Gold, GoldClaimRow, NoGold, load_f4_gold
from eval.f4.pred import F4Pred, load_predictions
from patent_ai.core.schemas.direction import AmendmentKind, DirectionCandidate, DirectionCandidates
from patent_ai.core.schemas.judgment_unit import JudgmentUnit

logger = logging.getLogger(__name__)

METRIC_NAME = "거친 방향 1등 일치율"
EXIT_NO_GOLD = 3  # 정답 없음: 성공(0)도 채점 실패(1)도 argparse 사용법 오류(2)도 아니다
FAILURE_KEYS = (
    "missing_prediction",  # 예측이 없는 OA (0점으로 셈)
    "uncovered_pairs",  # AI의 어느 묶음에도 없는 (거절이유, 청구항) 쌍
    "excluded_not_handled",  # 정답이 안 다룸이라 ② 채점에서 뺀 줄 (3절 13번)
    "excluded_needs_human_judgment",  # 1등 후보가 없는 묶음(확신 낮음·후보 0개)이라 ②에서 뺀 줄
    "excluded_branch_conflict",  # 같은 크기 묶음끼리 AI 값이 엇갈려 뺀 줄 (3절 5번)
)
_ABSTAIN = "abstain"  # 1등 후보가 없음 (직접 판단 필요)
_KEEPS_PARENT = (AmendmentKind.UNCHANGED, AmendmentKind.CORRECT_ERROR)


def _top(result: DirectionCandidates) -> DirectionCandidate | None:
    return next((c for c in result.candidates if c.rank == 1), None)


def claim_direction(unit: JudgmentUnit, top: DirectionCandidate, claim: int) -> str:
    """1등 후보의 청구항별 보정 종류에서 그 청구항의 거친 방향을 계산한다 (정답 문서 4절 추천).

    종속항 글자가 그대로(또는 오기 정정뿐)이고 묶음의 독립항이 보정됐으면 독립항 값을 물려받는다.
    그 밖에는 그대로면 반박만, 보정이면 후보에 반박이 있으면 보정+반박, 없으면 보정만.
    삭제한 청구항은 후보에 반박이 있어도 보정만으로 센다 (정답 문서 2절 예시·3절 4번:
    후보의 반박은 묶음 것이고, 삭제한 항을 따로 반박하는지는 후보에 칸이 없다).
    """
    kinds = {a.claim: a.kind for a in top.amendment_core}
    rep = unit.representative_claim
    own = kinds.get(claim, AmendmentKind.UNCHANGED)
    rep_kind = kinds.get(rep, AmendmentKind.UNCHANGED)
    if claim != rep and own in _KEEPS_PARENT and rep_kind != AmendmentKind.UNCHANGED:
        own = rep_kind  # 물려받기 (3절 1·14번)
    if own == AmendmentKind.UNCHANGED:
        return "argue_only"
    if own == AmendmentKind.DELETE:
        return "amend_only"
    return "amend_and_argue" if top.rebuttal is not None else "amend_only"


def predicted(pred: F4Pred, row: GoldClaimRow) -> str | None:
    """정답 한 줄에 대한 AI 값: 거친 방향 / _ABSTAIN / None(어느 묶음에도 없음) / "conflict".

    그 청구항이 여러 묶음에 있으면 가장 작은 묶음에서 읽는다 (3절 5번).
    """
    units = [
        u
        for u in pred.units
        if u.rejection == row.rejection and row.claim in u.claims and u.unit_id in pred.directions
    ]
    if not units:
        return None
    smallest = min(len(u.claims) for u in units)
    values = set()
    for u in units:
        if len(u.claims) != smallest:
            continue
        top = _top(pred.directions[u.unit_id])
        values.add(_ABSTAIN if top is None else claim_direction(u, top, row.claim))
    return values.pop() if len(values) == 1 else "conflict"


@dataclass
class OAScore:
    """OA 한 통의 줄별 맞음/틀림. scores에는 합친 값만 싣는다."""

    handled: list[bool] = field(default_factory=list)  # ①
    direction: list[bool] = field(default_factory=list)  # ② 주 점수 (물려받은 줄 제외)
    direction_all: list[bool] = field(default_factory=list)  # ② 물려받은 줄 포함
    direction_strict: list[bool] = field(default_factory=list)  # ② 주 점수 + 보류를 틀림으로
    abstained: list[bool] = field(default_factory=list)  # ② 대상 줄(정답이 다룸)마다: 보류였나
    failures: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FAILURE_KEYS, 0))


def score_oa(g: F4Gold, pred: F4Pred | None) -> OAScore:
    s = OAScore()
    for row in g.claim_rows:
        value = predicted(pred, row) if pred is not None else None
        if pred is not None and value is None:
            s.failures["uncovered_pairs"] += 1
        # ① 다뤘나: 묶음에 있고 결과(후보나 직접 판단 필요)가 있으면 AI는 다룬 것
        s.handled.append(pred is not None and (value is not None) == row.handled)
        # ② 거친 방향
        if not row.handled:
            s.failures["excluded_not_handled"] += 1
            continue
        s.abstained.append(value == _ABSTAIN)
        if value == "conflict":
            s.failures["excluded_branch_conflict"] += 1
            continue
        if value == _ABSTAIN:
            s.failures["excluded_needs_human_judgment"] += 1
            if not row.inherited:
                s.direction_strict.append(False)
            continue
        ok = value == row.direction  # 묶음에 없는 줄(None)은 틀림
        s.direction_all.append(ok)
        if not row.inherited:
            s.direction.append(ok)
            s.direction_strict.append(ok)
    return s


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _set_mean(per_oa: list[OAScore], name: str) -> float | None:
    """OA마다 줄 평균 -> 채점한 줄이 있는 OA끼리 평균 (OA 한 통이 한 표)."""
    return _mean(
        [m for s in per_oa if (m := _mean([float(x) for x in getattr(s, name)])) is not None]
    )


def score_f4(
    cfg: F4EvalConfig,
    golds: dict[str, F4Gold],
    preds: dict[str, F4Pred],
    *,
    commit: str,
    gold_sha256: str,
) -> dict:
    """정답 OA마다 예측과 맞춰 scores dict를 만든다. 파일은 쓰지 않는다 (쓰기는 main)."""
    started = time.monotonic()
    if not golds:
        raise NoGold("F4 정답이 0개다")
    if not any(key in preds for key in golds):
        # 전부 빠졌으면 0점으로 성공하지 않는다 (조용한 실패 금지)
        raise EvalError("F4 예측이 하나도 정답 OA와 맞지 않는다")

    failures = dict.fromkeys(FAILURE_KEYS, 0)
    per_oa: list[OAScore] = []
    for key, g in golds.items():
        pred = preds.get(key)
        if pred is None:
            failures["missing_prediction"] += 1
        s = score_oa(g, pred)
        for name, count in s.failures.items():
            failures[name] += count
        per_oa.append(s)
    if failures["missing_prediction"]:
        logger.warning("F4 예측이 없는 OA %d건 (0점으로 셈)", failures["missing_prediction"])
    if failures["uncovered_pairs"]:
        logger.warning(
            "F4 대응 누락: 어느 묶음에도 없는 (거절이유, 청구항) %d쌍", failures["uncovered_pairs"]
        )

    metrics: dict[str, float] = {}
    for metric, name in (
        ("handled_accuracy", "handled"),
        ("direction_top1", "direction"),
        ("direction_top1_with_inherited", "direction_all"),
        ("direction_top1_strict", "direction_strict"),
        ("needs_human_judgment_rate", "abstained"),  # ② 대상 줄 가운데 보류로 빠진 비율
    ):
        value = _set_mean(per_oa, name)
        if value is None:
            logger.warning("F4 %s: 채점한 줄이 0개 (지표를 뺌)", metric)  # 0으로 쓰지 않는다
        else:
            metrics[metric] = value

    if "handled_accuracy" not in metrics:
        # 정답 줄이 하나도 없으면 잰 것이 없다. 빈 점수로 성공하지 않는다
        raise EvalError("F4 정답 청구항 줄이 0개라 채점한 것이 없다")

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
        "cost": {  # 채점은 모델을 부르지 않는다. 실행 비용은 예측을 만든 쪽 기록에서
            "usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "external_calls": 0,
            "seconds": round(time.monotonic() - started, 3),
        },
    }


# ---- 명령 (파일 읽기·쓰기)


def _gold_sha256(folder: Path) -> str:
    """정답 파일들을 이름 순서로 이어 붙인 해시 (정답이 바뀌었는지 scores에 남긴다)."""
    h = hashlib.sha256()
    for f in sorted(folder.glob("*.json")):
        h.update(f.read_bytes())
    return h.hexdigest()


def default_scores_dir(goldsets_root: Path, experiment: str) -> Path:
    """진짜 정답 폴더(…/data/goldsets)면 experiments/<실험>/, 아니면 work/f4/<실험>/."""
    if Path(goldsets_root).resolve().parts[-2:] == ("data", "goldsets"):
        return REPO_ROOT / "experiments" / experiment
    return REPO_ROOT / "work" / "f4" / experiment


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.f4.score")
    ap.add_argument("--config", required=True)
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument(
        "--predictions", required=True, help="run_f4 결과 JSON과 판단 단위 JSON 폴더 (git 밖)"
    )
    ap.add_argument(
        "--scores-dir",
        default=None,
        help="기본: 진짜 정답이면 experiments/<실험>/, 아니면 work/f4/<실험>/",
    )
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        check_experiment_name(cfg.experiment)
        pred_dir = Path(args.predictions)
        # 예측에는 OA·청구항 글자가 있어 git에 들어갈 수 있는 경로면 멈춘다
        if not is_git_ignored(pred_dir):
            raise EvalError(
                "예측 폴더가 git에 들어갈 수 있는 경로다 (저장소 밖이나 무시되는 경로만)"
            )
        root = Path(args.goldsets_root)
        folder = gold_path(root, cfg.goldset, cfg.gold)
        # 정답 폴더부터 본다: 없으면 다른 검사보다 먼저 "정답 없음"으로 끝낸다
        golds = load_f4_gold(folder, expected_version=cfg.goldset_version)
        check_goldset_version(root, cfg.goldset_version)
        preds = load_predictions(pred_dir)
        extra = set(preds) - set(golds)
        if extra:
            logger.warning("정답에 없는 예측 %d건 (채점에서 뺌)", len(extra))
        scores = score_f4(cfg, golds, preds, commit=git_commit(), gold_sha256=_gold_sha256(folder))
        scores_dir = (
            Path(args.scores_dir) if args.scores_dir else default_scores_dir(root, cfg.experiment)
        )
        write_scores(scores_dir, scores)
    except NoGold as e:
        # 가짜 점수를 쓰지 않는다. 성공으로 끝나지 않게 종료 코드도 따로 둔다
        logger.warning("F4 정답 없음: %s (scores.json을 쓰지 않음)", e)
        print(f"정답 없음: {e} (scores.json을 쓰지 않음)", file=sys.stderr)
        return EXIT_NO_GOLD
    except EvalError as e:
        print(f"채점 실패: {e}", file=sys.stderr)
        return 1
    print(f"scores.json 저장: n={scores['n']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
