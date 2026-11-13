"""생성 단계 설정과 API 키 읽기.

- 검색 후보(Phase 6 확정): 항 단위 3개 법령 코퍼스 + 질의 확장 v2 + M4a + LLM 재순위, 근거 5개.
- 키는 .env 에서만 읽고, 오류 메시지에 값을 넣지 않는다.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    corpus: Path = Path("data/processed/chunks_법령3_paragraph_split3000.jsonl")
    chunk_emb: Path = Path("data/processed/emb_text-embedding-3-small_chunks-law3_20261112-150833.json")
    expand_model: str = "gpt-5.4-mini-2026-03-17"
    rerank_model: str = "gpt-5.4-mini-2026-03-17"
    generation_model: str = "claude-sonnet-5-5"
    prompt_version: str = "v3"   # v2(봉인 평가에서 v1 대비 채택) + 존댓말 규칙(docs/experiment-results-generation.md 7장)
    n_evidence: int = 5          # 재순위 결과의 앞 몇 개를 근거로 쓰는지
    rerank_window: int = 10      # 재순위에 보내는 후보 수
    max_evidence_chars: int = 4000
    max_tokens: int = 6000  # 모델이 답 앞에 쓰는 내부 사고 토큰도 포함해서 넉넉히(2048 에서 답이 끊긴 적 있음)
    env_path: Path = Path(".env")
    article_corpus: Path = Path("data/processed/chunks_법령3_article.jsonl")  # 화면에서 인용 조문 원문을 보여 줄 때 읽는 파일
    port: int = 3000
    max_message_len: int = 1000


def load_key(name: str, env_path: Path = Path(".env")) -> str:
    """.env 의 NAME=값 줄에서 값을 읽는다. 없으면 이름만 담은 RuntimeError."""
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            if value:
                return value
    raise RuntimeError(f"{name} 값이 .env 에 없습니다")
