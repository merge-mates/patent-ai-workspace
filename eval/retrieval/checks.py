"""채점기 실행 전 검사 (design.md 2절 2번, 7-3 질의 누출 검사).

하나라도 걸리면 RetrievalEvalError. 메시지에는 row_id와 건수만 쓴다 (질의·정답 글자 금지).
"""

import re
from pathlib import Path

from eval.common import goldset
from eval.common.goldset import check_goldset_version
from eval.common.paths import REPO_ROOT, is_git_ignored
from eval.retrieval.config import RetrievalEvalConfig
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldItem, GoldRow
from patent_ai.retrieval.repository import ChunkRepository

# REPO_ROOT·is_git_ignored는 eval/common/paths.py에 있다 (score.py가 여기서 가져다 쓴다)
__all__ = ["REPO_ROOT", "find_leaks", "gold_path", "is_git_ignored", "preflight"]

# 번호 뒤에 숫자·소수점+숫자·℃·%·°가 오면 도면 번호가 아니다 ("도 3.5", "도 3%")
_NOT_AFTER_NUM = r"(?!\d|\.\d|[℃%°])"
# 괄호 속 문단 번호: [0023], [0022-0025], [23] (전각 【0023】·［0023］도)
_BRACKET = re.compile(r"[\[［【]\s*(\d+)\s*(?:[-~]\s*(\d+)\s*)?[\]］】]")


def _paragraph_leak(query: str, item: GoldItem) -> bool:
    """대괄호 문단 표기만 본다. 맨 숫자 0023은 소수와 구별이 안 돼 보지 않는다."""
    if item.start is None:
        # 정렬 키가 없으면 정답 라벨 글자가 질의에 그대로 있는지로 대신 본다
        return bool(item.label) and item.label in query
    end = item.end if item.end is not None else item.start
    for m in _BRACKET.finditer(query):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        # 질의의 번호 범위와 정답 범위가 겹치면 누출
        if lo <= end and item.start <= hi:
            return True
    return False


def _figure_leak(query: str, item: GoldItem) -> bool:
    for n in item.figures:
        # "도" 앞이 한글·영문·숫자면 "온도 300℃"처럼 다른 낱말이라 안 걸린다
        ko = rf"(?<!\w)(?:도면|도)\s*{n}{_NOT_AFTER_NUM}"
        en = rf"(?<![A-Za-z])fig\.?\s*{n}{_NOT_AFTER_NUM}"
        if re.search(ko, query) or re.search(en, query, re.IGNORECASE):
            return True
    return False


def _article_leak(query: str, item: GoldItem) -> bool:
    """정답 라벨(제29조 제2항)의 조 번호가 질의에 '제N조'/'N조'로 있으면 누출."""
    m = re.search(r"제?\s*(\d+)\s*조", item.label)
    if not m:
        return False
    return re.search(rf"(?<!\d)(?:제\s*)?{m.group(1)}\s*조", query) is not None


def _column_leak(query: str, item: GoldItem) -> bool:
    """칼럼 번호는 앞말(col., 칼럼)이 있을 때만 본다. 맨 3:10은 비율과 구별이 안 된다."""
    if item.start is None:
        return bool(item.label) and item.label in query
    end = item.end if item.end is not None else item.start
    for col in range(item.start // 10000, end // 10000 + 1):
        if re.search(
            rf"(?<![A-Za-z])(?:col\.?|column|칼럼|컬럼)\s*{col}(?!\d)", query, re.IGNORECASE
        ):
            return True
    return False


_DETECTORS = {
    "paragraph": _paragraph_leak,
    "figure": _figure_leak,
    "article": _article_leak,
    "column_line": _column_leak,
    # claim·abstract·page는 검사하지 않는다 ("제1항에 있어서"와 구별 불가, design 8절)
}


def find_leaks(row: GoldRow) -> list[str]:
    """질의에 정답 위치 표기가 든 항목을 '항목 번호(종류)'로 돌려준다 (질의 글자는 안 넣음)."""
    leaks = []
    for i, item in enumerate(row.items):
        detect = _DETECTORS.get(item.kind)
        if detect and detect(row.query, item):
            leaks.append(f"항목 {i}({item.kind})")
    return leaks


def gold_path(cfg: RetrievalEvalConfig, goldsets_root: Path) -> Path:
    """정답 파일 경로. `..`·절대 경로로 세트 폴더 밖을 가리키면 멈춘다 (eval/common)."""
    return goldset.gold_path(goldsets_root, cfg.goldset, cfg.gold)


def preflight(
    cfg: RetrievalEvalConfig,
    gold: list[GoldRow],
    repo: ChunkRepository,
    goldsets_root: Path,
    chunks_mode: bool,
    scores_dir: Path,
    cq_dir: Path,
) -> None:
    goldsets_root = Path(goldsets_root)
    gold_path(cfg, goldsets_root)  # 경로 모양 검사 (있는지는 load_gold가 본다)

    # 정답 세트 버전 (공통 검사)
    check_goldset_version(goldsets_root, cfg.goldset_version)

    # 색인 판
    if not repo.has_index_version(cfg.corpus, cfg.index_version):
        raise RetrievalEvalError(f"{cfg.corpus} 말뭉치에 색인 판 {cfg.index_version}이 없다")

    # 정답 0줄
    if not gold:
        raise RetrievalEvalError("정답 줄이 0개다")

    # 정답 줄 점검: 정답 파일은 말뭉치마다 나눈다. 다른 말뭉치 줄은 조용히 빼지 않고 멈춘다
    wrong_corpus = [row.row_id for row in gold if row.corpus != cfg.corpus]
    if wrong_corpus:
        raise RetrievalEvalError(
            f"설정 corpus({cfg.corpus})와 다른 corpus의 정답 줄 {len(wrong_corpus)}건: "
            + ", ".join(wrong_corpus)
        )
    # 인용문헌 줄은 doc_ids가 있어야 그 공보 안에서 채점된다 (없으면 점수가 부풀음)
    no_docs = [row.row_id for row in gold if row.corpus == "cite" and row.doc_ids is None]
    if no_docs:
        raise RetrievalEvalError(
            f"cite 줄에 doc_ids가 없다 {len(no_docs)}건: " + ", ".join(no_docs)
        )

    # 질의 누출: 걸린 줄의 row_id와 건수만 알린다
    leaked = {row.row_id: n for row in gold if (n := len(find_leaks(row)))}
    if leaked:
        ids = ", ".join(f"{rid}({n}항목)" for rid, n in leaked.items())
        raise RetrievalEvalError(f"질의에 정답 위치 표기가 있는 줄 {len(leaked)}건: {ids}")

    # 가짜 조각 점수가 experiments/ 에 섞이지 않게
    if chunks_mode:
        exp_root = (REPO_ROOT / "experiments").resolve()
        if Path(scores_dir).resolve().is_relative_to(exp_root):
            raise RetrievalEvalError("--chunks로 돌릴 때 scores 폴더는 experiments/ 아래일 수 없다")

    # CQ 후보에는 정답 위치·질의가 들어가므로 git에 들어갈 수 있는 경로면 멈춘다
    if not is_git_ignored(Path(cq_dir)):
        raise RetrievalEvalError(
            "cq 폴더가 git에 들어갈 수 있는 경로다 (저장소 밖이나 무시되는 경로만)"
        )
