"""F4 대응 방향 채점 (①②층). 규칙은 docs/evaluation/f4-direction-gold.md 2·3·5절.

채점 단위는 정답 한 줄 = OA 시점 청구항 × 거절이유. 청구항 점수 -> OA 평균 -> 세트 평균.
- ① 다뤘나: 지표 없음. 정의를 정답 문서에서 정한 뒤 다시 넣는다 (`handled`는 ② 대상 가르기용)
- ② 모델 1번 후보 거친 방향 일치율 (주 지표 direction_top1): 모델이 낸 1번 후보 =
  방향 후보 목록의 첫째(candidates[0])의 청구항별 보정 종류에서 계산한 방향이 정답과 같은가.
  확신 낮음(보류) 묶음도 빼지 않고 센다. 후보가 0개인 묶음은 틀림으로 센다.
  화면에서 순위를 숨기는 것(rank 없음)과 상관없이 목록 순서를 믿는다.
- 누락: 정답 줄 가운데 AI의 어느 묶음에도 없는 (거절이유, 청구항) 쌍 수 (failures)
확신도별 일치율(direction_top1_conf_high/medium/low)은 1번 후보의 확신도로 줄을 나눈다.
③④층, 실제 방향의 순위, 독립항만 점수는 아직 내지 않는다.
scores에는 출원번호·발송번호·원문 글자를 넣지 않는다 (건수와 비율만).

명령: uv run python eval/run_eval.py --config <설정> --predictions <폴더>
정답 폴더가 없으면 점수를 쓰지 않고 "정답 없음"으로 끝낸다 (종료 코드 EXIT_NO_GOLD).
비교용 direction_top1_ranked_only는 순위 1 후보로 센 값이고 보류(순위 1 후보 없음) 줄을 뺀다.
보류가 늘면 오를 수 있으므로 needs_human_judgment_rate와 같이 본다 (보류 비율은 ② 대상 줄 중
순위 1 후보가 없는 묶음의 비율).
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

METRIC_NAME = "모델 1번 후보 거친 방향 일치율"
EXIT_NO_GOLD = 3  # 정답 없음: 성공(0)도 채점 실패(1)도 argparse 사용법 오류(2)도 아니다
FAILURE_KEYS = (
    "missing_prediction",  # 예측이 없는 OA (0점으로 셈)
    "uncovered_pairs",  # AI의 어느 묶음에도 없는 (거절이유, 청구항) 쌍
    "excluded_not_handled",  # 정답이 안 다룸이라 ② 채점에서 뺀 줄 (3절 13번)
    "no_candidate",  # 후보가 0개인 묶음이라 1번 후보가 없는 줄 (주 지표에서 틀림으로 셈)
    "excluded_ranked_only_conflict",  # 순위 1 후보 방향이 가지끼리 엇갈려 ranked_only에서만 뺀 줄
    "excluded_ranked_only_abstain",  # 순위 1 후보가 없는 묶음이라 ranked_only에서만 뺀 줄
    "excluded_branch_conflict",  # 같은 크기 묶음끼리 AI 값이 엇갈려 뺀 줄 (3절 5번)
)
_ABSTAIN = "abstain"  # 순위 1 후보가 없음 (직접 판단 필요)
_NO_CANDIDATE = "no_candidate"  # 묶음에 후보가 0개라 1번 후보가 없음
CONFIDENCES = ("high", "medium", "low")
_KEEPS_PARENT = (AmendmentKind.UNCHANGED, AmendmentKind.CORRECT_ERROR)


def _rank1(result: DirectionCandidates) -> DirectionCandidate | None:
    """순위 1 후보 (화면에서 미리 고르는 후보). 확신 낮음 묶음에는 없다."""
    return next((c for c in result.candidates if c.rank == 1), None)


def _first(result: DirectionCandidates) -> DirectionCandidate | None:
    """모델이 낸 1번 후보 = 목록의 첫째. 순위가 없어도 목록 순서가 모델이 낸 순서다."""
    return result.candidates[0] if result.candidates else None


def claim_direction(unit: JudgmentUnit, top: DirectionCandidate, claim: int) -> str:
    """후보의 청구항별 보정 종류에서 그 청구항의 거친 방향을 계산한다 (정답 문서 4절 추천).

    종속항 글자가 그대로(또는 오기 정정뿐)이고 묶음 대표 독립항이 보정됐으면 그 값을 물려받는다.
    AI 결과에 인용 관계가 없어 중간 종속항만 보정된 줄은 물려받지 못한다 (정답 문서 4절, #39).
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


@dataclass
class Reading:
    """정답 한 줄에 대한 AI 값. 값은 거친 방향 / _NO_CANDIDATE / _ABSTAIN / "conflict"."""

    first: str  # 모델 1번 후보(목록 첫째)로 센 값 (주 지표)
    confidence: str | None  # 그 1번 후보의 확신도 (후보가 없으면 None)
    ranked: str  # 순위 1 후보로 센 값 (보류면 _ABSTAIN)


def predicted(pred: F4Pred, row: GoldClaimRow) -> Reading | None:
    """정답 한 줄에 대한 AI 읽기. 어느 묶음에도 없으면 None.

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
    firsts: set[str] = set()
    confidences: list[str] = []
    ranked: set[str] = set()
    for u in units:
        if len(u.claims) != smallest:
            continue
        result = pred.directions[u.unit_id]
        first, top = _first(result), _rank1(result)
        if first is None:
            firsts.add(_NO_CANDIDATE)
        else:
            firsts.add(claim_direction(u, first, row.claim))
            confidences.append(first.confidence)
        ranked.add(_ABSTAIN if top is None else claim_direction(u, top, row.claim))
    # 충돌은 방향 값으로만 가른다 (3절 5번의 "AI 값" = 방향). 확신도가 갈려도 충돌이 아니다.
    # 방향이 같고 확신도만 다르면 보수적으로 가장 낮은 확신도 칸에 넣는다.
    confidence = max(confidences, key=CONFIDENCES.index, default=None)
    return Reading(
        firsts.pop() if len(firsts) == 1 else "conflict",
        confidence,
        ranked.pop() if len(ranked) == 1 else "conflict",
    )


@dataclass
class OAScore:
    """OA 한 통의 줄별 맞음/틀림. scores에는 합친 값만 싣는다."""

    direction: list[bool] = field(default_factory=list)  # ② 주 점수 (1번 후보, 물려받은 줄 제외)
    direction_all: list[bool] = field(default_factory=list)  # ② 물려받은 줄 포함
    direction_ranked_only: list[bool] = field(default_factory=list)  # 순위 1 후보, 보류 줄 뺌
    abstained: list[bool] = field(default_factory=list)  # ② 대상 줄(정답이 다룸)마다: 보류였나
    by_confidence: dict[str, list[bool]] = field(
        default_factory=lambda: {c: [] for c in CONFIDENCES}
    )  # 주 점수를 1번 후보의 확신도로 나눈 것 (물려받은 줄 제외)
    failures: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FAILURE_KEYS, 0))


def score_oa(g: F4Gold, pred: F4Pred | None) -> OAScore:
    s = OAScore()
    for row in g.claim_rows:
        reading = predicted(pred, row) if pred is not None else None
        if pred is not None and reading is None:
            s.failures["uncovered_pairs"] += 1
        # ①층 다룸 지표는 정답 문서에서 정의를 정한 뒤 다시 넣는다 (지금은 재지 않음)
        # ② 거친 방향
        if not row.handled:
            s.failures["excluded_not_handled"] += 1
            continue
        s.abstained.append(reading is not None and reading.ranked == _ABSTAIN)
        # 비교용: 순위 1 후보로 센 값. 보류·가지 충돌 줄은 뺀다
        if reading is not None and reading.ranked == _ABSTAIN:
            s.failures["excluded_ranked_only_abstain"] += 1
        elif reading is not None and reading.ranked == "conflict":
            s.failures["excluded_ranked_only_conflict"] += 1
        else:
            ok_ranked = reading is not None and reading.ranked == row.direction
            if not row.inherited:
                s.direction_ranked_only.append(ok_ranked)
        # 주 점수: 모델 1번 후보로 센다. 보류 묶음도 뺀 채 두지 않는다
        if reading is not None and reading.first == "conflict":
            s.failures["excluded_branch_conflict"] += 1
            continue
        if reading is not None and reading.first == _NO_CANDIDATE:
            s.failures["no_candidate"] += 1  # 1번 후보가 없으니 틀림으로 센다
        ok = reading is not None and reading.first == row.direction  # 묶음에 없는 줄은 틀림
        s.direction_all.append(ok)
        if not row.inherited:
            s.direction.append(ok)
            if reading is not None and reading.confidence in s.by_confidence:
                s.by_confidence[reading.confidence].append(ok)
    return s


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _set_mean(per_oa: list[OAScore], name: str) -> float | None:
    """OA마다 줄 평균 -> 채점한 줄이 있는 OA끼리 평균 (OA 한 통이 한 표)."""
    return _mean_of_oas([getattr(s, name) for s in per_oa])


def _mean_of_oas(per_oa_values: list[list[bool]]) -> float | None:
    return _mean([m for xs in per_oa_values if (m := _mean([float(x) for x in xs])) is not None])


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
        ("direction_top1", "direction"),
        ("direction_top1_with_inherited", "direction_all"),
        ("direction_top1_ranked_only", "direction_ranked_only"),
        ("needs_human_judgment_rate", "abstained"),  # ② 대상 줄 가운데 보류로 빠진 비율
    ):
        value = _set_mean(per_oa, name)
        if value is None:
            logger.warning("F4 %s: 채점한 줄이 0개 (지표를 뺌)", metric)  # 0으로 쓰지 않는다
        else:
            metrics[metric] = value

    # 확신도별: 1번 후보의 확신도로 줄을 나눈다. 줄이 없는 단계는 0이 아니라 뺀다
    for conf in CONFIDENCES:
        metric = f"direction_top1_conf_{conf}"
        value = _mean_of_oas([s.by_confidence[conf] for s in per_oa])
        if value is None:
            logger.warning("F4 %s: 채점한 줄이 0개 (지표를 뺌)", metric)
        else:
            metrics[metric] = value
    # scores 공통 스키마에는 줄 수를 넣을 칸이 없어 로그로만 남긴다
    logger.info(
        "F4 확신도별 줄 수 (물려받은 줄 제외): %s",
        {c: sum(len(s.by_confidence[c]) for s in per_oa) for c in CONFIDENCES},
    )

    if not any(g.claim_rows for g in golds.values()):
        # 정답 줄이 하나도 없으면 잰 것이 없다. 빈 점수로 성공하지 않는다
        raise EvalError("F4 정답 청구항 줄이 0개라 채점한 것이 없다")
    if not metrics:
        # 줄은 있어도 전부 안 다룸이면 ② 대상이 없어 지표가 하나도 안 나온다
        raise EvalError("F4 채점한 지표가 없다 (정답 줄이 모두 안 다룸이라 ② 대상이 0개)")

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
