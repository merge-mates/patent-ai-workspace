"""F4 채점기 테스트: tmp_path에 손으로 만든 작은 정답·예측 (만든 번호, 원문 글자 없음).

기대값은 docs/evaluation/f4-direction-gold.md 2·3·4·5절과 구현 계획 C8에서 가져왔다.
"""

import json
import logging
from pathlib import Path

import pytest

import eval.run_eval as run_eval
from eval.common.errors import EvalError
from eval.common.scores import check_scores
from eval.f4.gold import F4Gold, load_f4_gold
from eval.f4.score import EXIT_NO_GOLD, main

KEY = "1020990000001_952099000000001"
KEY2 = "1020990000002_952099000000002"
OA = "oa_1"
UNV = {"value": "unverified", "reason": "input_unverified"}
OK = {"value": "confirmed", "checked": "테스트"}


# ---- 정답 (4절 JSON 모양) ----
def row(claim, rejection, direction, *, handled=True, inherited=False, kinds=("none",)):
    return {
        "claim": claim,
        "rejection": rejection,
        "handled": handled,
        "direction": direction,
        "inherited": inherited,
        "amend_kinds": list(kinds),
        "added_from": [],
        "argued": False,
    }


def gold(rows=None, version=2) -> dict:
    """2절 예시와 같은 사건: 청구항 1(독립)·2·3(종속) 진보성 + 청구항 2 명확성."""
    if rows is None:
        rows = [
            row(1, 1, "amend_and_argue", kinds=("add",)),
            row(2, 1, "amend_only", kinds=("delete",)),
            row(3, 1, "amend_and_argue", inherited=True),
            row(2, 2, "amend_only", kinds=("clarify",)),
        ]
    return {
        "gold_version": version,
        "source": {"opinion": "1-1-2099-0000001-01", "amendment": "1-1-2099-0000002-01"},
        "reviewed": {"by": None, "date": None},
        "new_claims": 0,
        "claim_rows": rows,
    }


# ---- 예측 (JudgmentUnit 목록 + DirectionCandidates 목록) ----
def unit(rejection, article, claims, *, order=1) -> dict:
    clarity = article == "42-4-2"
    return {
        "status": OK,
        "unit_id": f"{OA}:{article}:c{claims[0]}",
        "rejection": rejection,
        "rejection_kind": "clarity" if clarity else "inventive_step",
        "unit_kind": "single_claim" if clarity else "independent_group",
        "representative_claim": claims[0],
        "claims": claims,
        "order": order,
    }


def cand(u, n, rank, coarse, core) -> dict:
    low = rank is None
    rebuttal_type = "obvious_error" if u["rejection_kind"] == "clarity" else "difference"
    return {
        "status": UNV,
        "candidate_id": f"{u['unit_id']}:d{n}",
        "rank": rank,
        "coarse": coarse,
        "name": "만든 방향",
        "confidence": "low" if low else "high",
        "reason": "만든 이유",
        "checks": [],
        "per_rejection": [{"rejection": u["rejection"], "response": "만든 대응"}],
        "amendment_core": core,
        "rebuttal": None
        if coarse == "amend_only"
        else {"rejection_kind": u["rejection_kind"], "type": rebuttal_type, "summary": "만든 요지"},
        "flags": ["needs_human_judgment"] if low else [],
    }


def group(u, cands) -> dict:
    first = next((c for c in cands if c["rank"] == 1), None)
    return {
        "status": UNV if cands else {"value": "unverified", "reason": "not_extracted"},
        "unit_id": u["unit_id"],
        "candidates": cands,
        "selection": {"candidate_id": first["candidate_id"], "origin": "ai_default"}
        if first
        else None,
        "amendment_limit": {"value": "initial", "status": OK},
        "flags": [] if first else ["needs_human_judgment"],
    }


ADD = {"claim": 1, "kind": "add", "source": "other_dependent"}
DELETE = {"claim": 2, "kind": "delete"}
CLARIFY = {"claim": 2, "kind": "clarify"}


def prediction(*, inventive_claims=(1, 2, 3), clarity_low=False, argue_first=False):
    """진보성 묶음: 1등이 청구항 1 부가 + 청구항 2 삭제 + 반박. 명확성 묶음: 1등이 명확화만.

    argue_first면 진보성 묶음의 1번 후보(목록 첫째)를 보정 없이 반박으로 바꾼다.
    """
    u1 = unit(1, "29-2", list(inventive_claims))
    u2 = unit(2, "42-4-2", [2], order=2)
    amend, argue = (2, 1) if argue_first else (1, 2)
    cands = [
        cand(u1, 1, amend, "amend_and_argue", [ADD, DELETE]),
        cand(u1, 2, argue, "argue_only", []),
    ]
    if argue_first:
        cands.reverse()  # 모델이 낸 순서: 반박만 후보가 목록 첫째 (1번 후보)
    g1 = group(u1, cands)
    if clarity_low:
        g2 = group(u2, [cand(u2, 1, None, "amend_only", [CLARIFY])])
    else:
        g2 = group(u2, [cand(u2, 1, 1, "amend_only", [CLARIFY])])
    return [u1, u2], [g1, g2]


def f4_output(directions) -> dict:
    """F4Output dump 모양 (채점기는 directions만 쓴다)."""
    return {
        "oa_id": OA,
        "directions": directions,
        "drafts": None,
        "held_units": [],
        "unsupported_rejections": [],
        "uncovered": [],
        "amendment_limit_applied": False,
        "status": UNV,
        "flags": [],
    }


# ---- 폴더 차리기 ----
class Env:
    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "goldsets"
        self.gold_dir = self.root / "tune" / "f4"
        self.preds = tmp_path / "preds"
        self.out = tmp_path / "out"
        self.root.mkdir()
        self.preds.mkdir()
        (self.root / "VERSION").write_text("2\n")
        self.cfg = tmp_path / "config.yaml"
        self.cfg.write_text(
            "experiment: m2-f4-x\nfeature: f4\ngoldset: tune\ngoldset_version: 2\nimpl: skeleton\n",
            encoding="utf-8",
        )

    def put_gold(self, data: dict, key: str = KEY) -> None:
        self.gold_dir.mkdir(parents=True, exist_ok=True)
        (self.gold_dir / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")

    def put_pred(self, units, directions, key: str = KEY, *, as_list=False) -> None:
        body = directions if as_list else f4_output(directions)
        (self.preds / f"{key}.json").write_text(json.dumps(body), encoding="utf-8")
        (self.preds / f"{key}.units.json").write_text(json.dumps(units), encoding="utf-8")

    @property
    def args(self) -> list[str]:
        return [
            "--config",
            str(self.cfg),
            "--goldsets-root",
            str(self.root),
            "--predictions",
            str(self.preds),
            "--scores-dir",
            str(self.out),
        ]

    def scores(self) -> dict:
        return json.loads((self.out / "scores.json").read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ---- ①②층 일치율 ----
def test_1등_후보에서_청구항별_방향을_계산해_정답과_맞춘다(env):
    env.put_gold(gold())
    env.put_pred(*prediction())
    assert main(env.args) == 0
    s = env.scores()
    m = s["metrics"]
    assert m["handled_accuracy"] == 1.0  # ①: 네 줄 모두 다룸
    # ② 주 점수(물려받은 줄 제외): 청구항 1 보정+반박 맞음, 삭제한 청구항 2는 후보에 반박이
    # 있어도 보정만(정답 문서 2절 예시)이라 맞음, 명확성 청구항 2 맞음 -> 3/3
    assert m["direction_top1"] == 1.0
    # 물려받은 청구항 3(글자 그대로, 독립항이 보정됨)은 독립항 값을 물려받아 맞음 -> 4/4
    assert m["direction_top1_with_inherited"] == 1.0
    assert m["needs_human_judgment_rate"] == 0.0
    assert s["failures"]["uncovered_pairs"] == 0
    assert s["failures"]["missing_prediction"] == 0
    assert s["n"] == 1


def test_1등_방향이_정답과_다르면_틀림으로_센다(env):
    env.put_gold(gold())
    env.put_pred(*prediction(argue_first=True))  # 진보성 묶음 1등이 보정 없이 반박
    assert main(env.args) == 0
    m = env.scores()["metrics"]
    # 진보성 줄(청구항 1·2)은 반박만으로 계산돼 틀리고, 명확성 줄만 맞음
    assert m["direction_top1"] == pytest.approx(1 / 3)
    assert m["direction_top1_with_inherited"] == pytest.approx(1 / 4)
    assert m["handled_accuracy"] == 1.0  # 방향이 틀려도 다룬 것은 맞음


def test_scores_json은_공통_스키마를_통과하고_번호를_담지_않는다(env):
    env.put_gold(gold())
    env.put_pred(*prediction())
    assert main(env.args) == 0
    s = env.scores()
    check_scores(s)  # experiments/_template/scores.schema.json 필수 칸·꼴
    assert (s["experiment"], s["goldset"], s["goldset_version"]) == ("m2-f4-x", "tune", 2)
    assert s["impl"] == "skeleton" and s["commit"] and len(s["gold_sha256"]) == 64
    assert s["cost"]["external_calls"] == 0 and s["cost"]["usd"] == 0
    text = (env.out / "scores.json").read_text(encoding="utf-8")
    assert "1020990000001" not in text and "952099000000001" not in text


def test_예측이_DirectionCandidates_목록이어도_읽는다(env):
    env.put_gold(gold())
    env.put_pred(*prediction(argue_first=True), as_list=True)
    assert main(env.args) == 0
    assert env.scores()["metrics"]["direction_top1"] == pytest.approx(1 / 3)


def test_안_다룸_줄은_방향_채점에서_빼고_건수를_남긴다(env):
    rows = gold()["claim_rows"] + [row(3, 2, None, handled=False)]
    env.put_gold(gold(rows))
    env.put_pred(*prediction())
    assert main(env.args) == 0
    s = env.scores()
    assert s["metrics"]["direction_top1"] == 1.0  # 그대로
    assert s["failures"]["excluded_not_handled"] == 1
    # ①: 정답은 안 다룸, AI는 그 (거절이유, 청구항)을 어느 묶음에도 두지 않음 -> 일치
    assert s["metrics"]["handled_accuracy"] == 1.0
    assert s["failures"]["uncovered_pairs"] == 1  # 그래도 대상 청구항이 빠진 것은 누락으로 센다


# ---- 누락 ----
def test_어느_묶음에도_없는_거절이유_청구항_쌍을_누락으로_센다(env, caplog):
    env.put_gold(gold())
    env.put_pred(*prediction(inventive_claims=(1, 2)))  # 청구항 3이 진보성 묶음에서 빠짐
    with caplog.at_level(logging.WARNING):
        assert main(env.args) == 0
    s = env.scores()
    assert s["failures"]["uncovered_pairs"] == 1
    assert s["metrics"]["handled_accuracy"] == pytest.approx(3 / 4)
    # 빠진 줄은 방향도 틀림: 주 점수는 그대로(물려받은 줄이라 제외), 포함 점수는 3/4
    assert s["metrics"]["direction_top1"] == 1.0
    assert s["metrics"]["direction_top1_with_inherited"] == pytest.approx(3 / 4)
    assert "누락" in caplog.text


# ---- 확신 낮음 (직접 판단 필요): 주 지표는 모델 1번 후보(목록 첫째)로 모든 묶음을 센다 ----
def low_clarity(units, directions, *, wrong=False):
    """명확성 묶음의 후보를 확신 낮음(rank 없음)으로 두고, wrong이면 방향이 정답과 달라지게 한다."""
    if wrong:
        c = directions[1]["candidates"][0]
        c["coarse"], c["amendment_core"], c["rebuttal"] = (
            "argue_only",
            [],
            {
                "rejection_kind": "clarity",
                "type": "obvious_error",
                "summary": "만든 요지",
            },
        )
    return units, directions


def test_확신_낮은_묶음도_1번_후보가_맞으면_주_지표에서_맞음으로_센다(env):
    env.put_gold(gold())
    env.put_pred(*prediction(clarity_low=True))
    assert main(env.args) == 0
    s = env.scores()
    m = s["metrics"]
    assert m["direction_top1"] == 1.0  # 보류 묶음 줄도 빼지 않고 3/3
    assert m["direction_top1_ranked_only"] == 1.0  # 보류 줄을 뺀 2/2 (비교용)
    assert m["needs_human_judgment_rate"] == pytest.approx(1 / 4)  # ② 대상 4줄 중 1줄
    assert s["failures"]["excluded_ranked_only_abstain"] == 1
    assert s["failures"]["no_candidate"] == 0
    assert "direction_top1_strict" not in m
    assert m["handled_accuracy"] == 1.0
    assert s["failures"]["uncovered_pairs"] == 0


def test_확신_낮은_묶음의_1번_후보가_틀리면_주_지표에서_틀림이다(env):
    env.put_gold(gold())
    env.put_pred(*low_clarity(*prediction(clarity_low=True), wrong=True))
    assert main(env.args) == 0
    m = env.scores()["metrics"]
    assert m["direction_top1"] == pytest.approx(2 / 3)
    assert m["direction_top1_ranked_only"] == 1.0  # 보류 줄을 빼므로 그대로


def test_후보가_0개인_묶음은_틀림으로_세고_건수를_남긴다(env):
    env.put_gold(gold())
    units, directions = prediction()
    directions[1] = group(units[1], [])  # 명확성 묶음 후보 0개
    env.put_pred(units, directions)
    assert main(env.args) == 0
    s = env.scores()
    assert s["metrics"]["direction_top1"] == pytest.approx(2 / 3)  # 빼지 않고 틀림
    assert s["metrics"]["direction_top1_ranked_only"] == 1.0
    assert s["failures"]["no_candidate"] == 1
    assert s["failures"]["excluded_ranked_only_abstain"] == 1
    assert s["metrics"]["needs_human_judgment_rate"] == pytest.approx(1 / 4)
    assert s["failures"]["uncovered_pairs"] == 0  # 묶음에는 있다


def test_목록_첫째가_확신_낮음이고_순위_있는_후보가_둘째면_첫째로_센다(env):
    env.put_gold(gold())
    units, directions = prediction()
    u1 = units[0]
    directions[0] = group(
        u1,
        [
            cand(u1, 1, None, "argue_only", []),  # 첫째: 확신 낮음, 반박만
            cand(u1, 2, 1, "amend_and_argue", [ADD, DELETE]),  # 둘째: rank 1
        ],
    )
    env.put_pred(units, directions)
    assert main(env.args) == 0
    m = env.scores()["metrics"]
    assert m["direction_top1"] == pytest.approx(1 / 3)  # 첫째(반박만) 기준: 진보성 두 줄 틀림
    assert m["direction_top1_ranked_only"] == 1.0  # rank 1 후보 기준: 전부 맞음
    assert m["direction_top1_with_inherited"] == pytest.approx(1 / 4)
    assert m["needs_human_judgment_rate"] == 0.0  # rank 1 후보가 있으니 보류 아님


def test_확신도별_일치율은_1번_후보의_확신도로_줄을_나눈다(env, caplog):
    env.put_gold(gold())
    # 진보성 묶음 1번 후보(rank 1) 확신 높음 -> 청구항 1·2 맞음. 명확성 1번 후보는 낮음+틀림
    units, directions = low_clarity(*prediction(clarity_low=True), wrong=True)
    # 물려받은 청구항 3을 틀리게: 확신도 칸에 섞이면 high가 2/3으로 내려간다
    directions[0]["candidates"][0]["amendment_core"].append({"claim": 3, "kind": "delete"})
    env.put_pred(units, directions)
    with caplog.at_level(logging.WARNING):
        assert main(env.args) == 0
    m = env.scores()["metrics"]
    assert m["direction_top1_with_inherited"] == pytest.approx(2 / 4)  # 청구항 3과 명확성 줄이 틀림
    assert m["direction_top1_conf_high"] == 1.0  # 진보성 2줄 맞음 (물려받은 줄 제외)
    assert m["direction_top1_conf_low"] == 0.0  # 명확성 1줄 틀림
    assert "direction_top1_conf_medium" not in m  # 줄 없는 단계는 0이 아니라 뺌
    assert "direction_top1_conf_medium" in caplog.text  # 경고


def test_확신도별_지표는_중간_단계도_가른다(env):
    env.put_gold(gold())
    units, directions = prediction()
    directions[1]["candidates"][0]["confidence"] = "medium"
    env.put_pred(units, directions)
    assert main(env.args) == 0
    m = env.scores()["metrics"]
    assert m["direction_top1_conf_medium"] == 1.0
    assert m["direction_top1_conf_high"] == 1.0
    assert "direction_top1_conf_low" not in m


def test_줄_수는_scores에_넣지_않고_로그로_남긴다(env, caplog):
    env.put_gold(gold())
    env.put_pred(*prediction(clarity_low=True))
    with caplog.at_level(logging.INFO):
        assert main(env.args) == 0
    check_scores(env.scores())  # 공통 스키마 통과 (새 최상위 칸 없음)
    assert set(env.scores()) == {
        "experiment", "commit", "goldset", "goldset_version", "gold_sha256", "impl",
        "metric_name", "n", "metrics", "failures", "cost",
    }  # fmt: skip
    # 줄 수: 높음 = 진보성 청구항 1·2, 낮음 = 명확성 청구항 2 (물려받은 청구항 3 제외)
    assert "확신도별 줄 수 (물려받은 줄 제외): {'high': 2, 'medium': 0, 'low': 1}" in caplog.text


def test_물려받지_않은_줄이_어느_묶음에도_없으면_주_지표에서_틀림이다(env):
    rows = gold()["claim_rows"] + [row(4, 1, "amend_only", kinds=("delete",))]
    env.put_gold(gold(rows))
    env.put_pred(*prediction())  # 청구항 4는 어느 묶음에도 없음
    assert main(env.args) == 0
    s = env.scores()
    assert s["failures"]["uncovered_pairs"] == 1
    assert s["metrics"]["direction_top1"] == pytest.approx(3 / 4)  # 빼지 않고 틀림
    assert s["metrics"]["direction_top1_ranked_only"] == pytest.approx(3 / 4)


# ---- 가지 충돌: 같은 크기 묶음 둘이 같은 (거절이유, 청구항)을 담음 (3절 5번) ----
def make_twin() -> dict:
    """진보성 묶음과 같은 크기(청구항 1·2·3)의 쌍둥이 묶음 (unit_id 끝 /a는 가지 표시)."""
    twin = unit(1, "29-2", [1, 2, 3])
    twin["unit_id"] += "/a"
    return twin


def with_twin(units, directions, cands):
    """쌍둥이 묶음과 그 후보를 더한다."""
    twin = make_twin()
    return [*units, twin], [*directions, group(twin, cands)]


def test_가지의_1번_후보_방향이_엇갈리면_주_지표에서_빼고_센다(env):
    env.put_gold(gold())
    units, directions = prediction()
    twin_u = make_twin()
    cands = [cand(twin_u, 1, 1, "argue_only", [])]  # 반박만: 원래 묶음(보정+반박)과 엇갈림
    env.put_pred(*with_twin(units, directions, cands))
    assert main(env.args) == 0
    s = env.scores()
    assert s["failures"]["excluded_branch_conflict"] == 3  # 진보성 청구항 1·2·3
    assert s["failures"]["excluded_ranked_only_conflict"] == 3
    assert s["metrics"]["direction_top1"] == 1.0  # 남은 명확성 줄만


def test_가지의_방향은_같고_확신도만_다르면_셈하고_낮은_확신도_칸에_넣는다(env):
    env.put_gold(gold())
    units, directions = prediction()
    twin_u = make_twin()
    twin_cand = cand(twin_u, 1, 1, "amend_and_argue", [ADD, DELETE])
    twin_cand["confidence"] = "medium"  # 원래 묶음 1번 후보는 high
    env.put_pred(*with_twin(units, directions, [twin_cand]))
    assert main(env.args) == 0
    s = env.scores()
    assert s["failures"]["excluded_branch_conflict"] == 0
    assert s["failures"]["excluded_ranked_only_conflict"] == 0
    assert s["metrics"]["direction_top1"] == 1.0  # 충돌이 아니라 셈
    assert s["metrics"]["direction_top1_conf_medium"] == 1.0  # 진보성 2줄: 더 낮은 쪽 칸
    assert s["metrics"]["direction_top1_conf_high"] == 1.0  # 명확성 줄만 남음


def test_순위_1_후보만_엇갈리면_ranked_only에서만_빼고_센다(env):
    env.put_gold(gold())
    units, directions = prediction()
    twin_u = make_twin()
    cands = [
        cand(twin_u, 1, None, "amend_and_argue", [ADD, DELETE]),  # 첫째는 같은 방향, 확신 낮음
        cand(twin_u, 2, 1, "argue_only", []),  # rank 1은 반박만: 원래 묶음과 엇갈림
    ]
    env.put_pred(*with_twin(units, directions, cands))
    assert main(env.args) == 0
    s = env.scores()
    assert s["failures"]["excluded_branch_conflict"] == 0  # 1번 후보 방향은 같다
    assert s["failures"]["excluded_ranked_only_conflict"] == 3
    assert s["metrics"]["direction_top1"] == 1.0
    assert s["metrics"]["direction_top1_conf_low"] == 1.0  # 쌍둥이 첫째가 낮음 -> 낮음 칸


# ---- 예측 없음 ----
def test_예측이_없는_OA는_0점이고_실패_유형에_남는다(env, caplog):
    env.put_gold(gold())
    env.put_gold(gold(), KEY2)
    env.put_pred(*prediction())  # KEY만
    with caplog.at_level(logging.WARNING):
        assert main(env.args) == 0
    s = env.scores()
    assert s["n"] == 2 and s["failures"]["missing_prediction"] == 1
    # OA 한 통이 한 표: (점수 + 0) / 2
    assert s["metrics"]["handled_accuracy"] == pytest.approx(0.5)
    assert s["metrics"]["direction_top1"] == pytest.approx(0.5)
    assert "예측이 없는" in caplog.text


def test_예측이_하나도_없으면_0점으로_성공하지_않는다(env, capsys):
    env.put_gold(gold())
    assert main(env.args) == 1
    assert not (env.out / "scores.json").exists()
    assert "예측" in capsys.readouterr().err


def test_결과_안에_든_판단_단위로_채점한다(env):
    env.put_gold(gold())
    units, directions = prediction()
    body = {**f4_output(directions), "units": units}  # run_f4 결과에 units가 실려 있음
    (env.preds / f"{KEY}.json").write_text(json.dumps(body), encoding="utf-8")
    assert not (env.preds / f"{KEY}.units.json").exists()  # 따로 둔 파일 없이
    assert main(env.args) == 0
    s = env.scores()
    assert s["metrics"]["direction_top1"] == 1.0 and s["failures"]["uncovered_pairs"] == 0


def test_결과_안_판단_단위가_따로_둔_파일보다_먼저다(env):
    env.put_gold(gold())
    units, directions = prediction()
    env.put_pred(units[:1], directions)  # 따로 둔 파일에는 명확성 묶음이 빠져 있음
    body = {**f4_output(directions), "units": units}
    (env.preds / f"{KEY}.json").write_text(json.dumps(body), encoding="utf-8")
    assert main(env.args) == 0
    assert env.scores()["failures"]["uncovered_pairs"] == 0  # 결과 안의 것을 썼다


def test_결과_안_판단_단위_모양이_틀리면_멈춘다(env, capsys):
    env.put_gold(gold())
    units, directions = prediction()
    body = {**f4_output(directions), "units": [{"unit_id": "x"}]}
    (env.preds / f"{KEY}.json").write_text(json.dumps(body), encoding="utf-8")
    assert main(env.args) == 1
    assert "판단 단위" in capsys.readouterr().err


def test_판단_단위_파일이_없으면_멈춘다(env, capsys):
    env.put_gold(gold())
    env.put_pred(*prediction())
    (env.preds / f"{KEY}.units.json").unlink()
    assert main(env.args) == 1
    assert "판단 단위" in capsys.readouterr().err
    assert not (env.out / "scores.json").exists()


def test_예측_모양이_틀리면_멈춘다(env, capsys):
    env.put_gold(gold())
    env.put_pred(*prediction())
    (env.preds / f"{KEY}.json").write_text('{"directions": [{"unit_id": "x"}]}', encoding="utf-8")
    assert main(env.args) == 1
    err = capsys.readouterr().err
    assert "예측 파일 1번째" in err and "1020990000001" not in err


def test_예측_폴더의_summary_json은_건너뛰고_경고한다(env, caplog):
    env.put_gold(gold())
    env.put_pred(*prediction())
    (env.preds / "summary.json").write_text('[{"case": "case1", "ok": true}]', encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert main(env.args) == 0
    assert env.scores()["n"] == 1
    assert "OA 키 꼴이 아닌 파일 1개" in caplog.text


def test_키_꼴인데_깨진_예측_파일은_건너뛰지_않고_실패한다(env, capsys):
    env.put_gold(gold())
    env.put_pred(*prediction())
    (env.preds / f"{KEY2}.json").write_text('[{"case": "case1"}]', encoding="utf-8")
    assert main(env.args) == 1
    assert "모양이 아니다" in capsys.readouterr().err


# ---- 정답 없음 ----
def test_정답_폴더가_없으면_정답_없음으로_끝나고_점수_파일을_쓰지_않는다(env, capsys, caplog):
    env.put_pred(*prediction())
    with caplog.at_level(logging.WARNING):
        code = main(env.args)
    # 성공(0)도 채점 실패(1)도 argparse 사용법 오류(2)도 아님
    assert code == EXIT_NO_GOLD == 3
    assert not (env.out / "scores.json").exists()
    assert "정답 없음" in capsys.readouterr().err
    assert "정답 없음" in caplog.text


def test_정답_폴더가_비어_있어도_정답_없음(env, capsys):
    env.gold_dir.mkdir(parents=True)
    assert main(env.args) == EXIT_NO_GOLD
    assert not (env.out / "scores.json").exists()


def test_정답_줄이_하나도_없으면_빈_점수로_성공하지_않는다(env, capsys):
    env.put_gold(gold(rows=[]))
    env.put_pred(*prediction())
    assert main(env.args) == 1
    assert "0개" in capsys.readouterr().err
    assert not (env.out / "scores.json").exists()


def test_판단_단위에_없는_묶음의_방향_결과는_버리고_경고한다(env, caplog):
    env.put_gold(gold())
    units, directions = prediction()
    env.put_pred(units[:1], directions)  # 명확성 묶음의 판단 단위가 빠짐
    with caplog.at_level(logging.WARNING):
        assert main(env.args) == 0
    assert "판단 단위 파일에 없는" in caplog.text
    assert env.scores()["failures"]["uncovered_pairs"] == 1  # 그 묶음의 줄은 누락으로 셈


# ---- 정답 모양 ----
@pytest.mark.parametrize(
    "broken",
    [
        lambda g: g.pop("claim_rows"),  # 칸 빠짐
        lambda g: g["claim_rows"][0].update(direction="argue"),  # 모르는 방향 값
        lambda g: g["claim_rows"][0].update(extra_field=1),  # 모르는 칸
        lambda g: g["claim_rows"][0].update(handled=False),  # 안 다룸인데 방향이 있음
        lambda g: g["claim_rows"][0].update(direction=None),  # 다룸인데 방향이 없음
        lambda g: g["claim_rows"].append(dict(g["claim_rows"][0])),  # 같은 줄 두 번
        lambda g: g["claim_rows"][0].update(amend_kinds=["rewrite"]),  # 모르는 보정 종류
    ],
)
def test_정답_모양이_틀리면_오류로_멈춘다(env, capsys, broken):
    data = gold()
    broken(data)
    env.put_gold(data)
    env.put_pred(*prediction())
    assert main(env.args) == 1
    err = capsys.readouterr().err
    assert "정답 파일 1번째" in err and "1020990000001" not in err
    assert not (env.out / "scores.json").exists()


def test_정답_판이_설정과_다르면_멈춘다(env, capsys):
    env.put_gold(gold(version=1))
    env.put_pred(*prediction())
    assert main(env.args) == 1
    assert "gold_version" in capsys.readouterr().err


def test_정답_읽기는_문서_4절_예시를_그대로_받는다(tmp_path):
    example = {
        "gold_version": 2,
        "source": {"opinion": "접수번호", "amendment": None},
        "reviewed": {"by": None, "date": None},
        "new_claims": 0,
        "claim_rows": [
            {"claim": 1, "rejection": 1, "handled": True, "direction": "amend_and_argue",
             "inherited": False, "amend_kinds": ["add"], "added_from": ["claim:2"], "argued": True},
            {"claim": 3, "rejection": 1, "handled": True, "direction": "amend_and_argue",
             "inherited": True, "amend_kinds": ["none"], "added_from": [], "argued": False},
        ],
    }  # fmt: skip
    assert len(F4Gold.model_validate(example).claim_rows) == 2
    with pytest.raises(EvalError):
        load_f4_gold(tmp_path / "nope", expected_version=2)


# ---- 채점 명령 하나로 불림 ----
def test_run_eval이_feature_f4로_이_채점기를_부른다(env):
    assert run_eval.SCORERS["f4"] is main
    env.put_gold(gold())
    env.put_pred(*prediction())
    assert run_eval.main(env.args) == 0
    assert env.scores()["n"] == 1
