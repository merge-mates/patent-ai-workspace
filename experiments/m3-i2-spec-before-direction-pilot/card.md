# 대응 방향 선택 전 최초 명세서 문단 파일럿

2026-11-24 · tune 4건 · 조건별 모델 실행 1회. 개선의 재현성과 전체 초안 품질은 별도 검증한다.

| 조건 | 대응 방향 일치 행 | 보정안에서 실제 제출본의 근거 문단을 하나 이상 쓴 행 |
|---|---:|---:|
| 기존 | 8/17 | 1/10 |
| BM25 문단 제공 | 11/17 | 3/10 |
| 확인된 원문 문단 제공 | 10/17 | 5/10 |

청구항 원문과 청구항 원문에 OA의 거절 설명을 붙인 질의는 각각 38개였다. 근거 문단 골드가 있는 신규성·진보성 10행의 Recall@10은 두 조건 모두 0.3167이며, 5행에서 한 문단 이상 찾았다. MRR@10은 0.1036과 0.0869였다. 명확성의 보정 근거 골드 1행은 검색 실험 범위에서 제외했다. 골드에 기록된 문단은 추출본에 모두 존재했다.

CLI 기준은 `04af9b2264c44e009f9f1f9eb3e5fabde1d87ebc`의 트리와 같다. 원래 실행은 `510428a`에 같은 diff를 더해 실행했고 지문을 로컬 `cli-run-settings.json`에 기록했다. 인용문헌은 `cite-idx-v5` 및 `gemini-embedding-001` 1536차원을 사용했다. 평가 실행기는 인용문헌 검색에서 심사관 지정 위치를 출발점으로 쓰는 설정을 껐다. 세 방향 조건은 각 OA의 같은 앞 단계 결과를 재사용했다.

## 재현

로컬 출력 디렉터리에 `manifest.json`, `cli-baseline/`, `spec-retrieval/`, `draft-comparison/<case>/common-input.json`이 있어야 한다. 상세 골드와 실제 질의·원문·응답·사건 식별자는 로컬에만 둔다. 재실행 출력을 별도 폴더에 쓴다.

```sh
PILOT_SCRIPTS=experiments/m3-i2-spec-before-direction-pilot
PILOT_RUN=work/e2e_2026-11-24_oa4
uv run python "$PILOT_SCRIPTS/report.py" "$PILOT_RUN" \
  --citation-gold data/goldsets/tune/retrieval/cite_gold.jsonl
uv run python "$PILOT_SCRIPTS/spec_retrieval.py" "$PILOT_RUN" \
  --detail-gold data/goldsets/tune/f4_detail --output "$PILOT_RUN/replay-retrieval"
PYTHONPATH=. uv run python "$PILOT_SCRIPTS/compare_drafts.py" "$PILOT_RUN" \
  --gold data/goldsets/tune/f4 --output "$PILOT_RUN/replay-prepared" --prepare-only
```

모델 실행은 프로젝트의 환경 구성을 사용해 `--prepare-only`를 빼고 실행한다. `--case` 또는 `--variant`로 범위를 줄일 수 있다. 검색 재현 스크립트는 현재 기준선의 저장된 OA를 쓰므로 11월 23일 저장본을 사용한 최초 검색과 OA 요약 문구가 달라질 수 있다. 실제 사용 질의는 `query-audit/`와 원본 JSONL에서 확인한다.

법률 검색 로그에는 질문과 결과 건수, 선택한 근거가 보존됐다. 조문 검색 골드와 전체 순위는 이 파일럿의 기록에 없다. 인용 검색의 구성요소 질의는 저장된 대비와 모델 캐시에서 일치 해시를 찾아 보고서에 복원한다.
