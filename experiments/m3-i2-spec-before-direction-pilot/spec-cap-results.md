# 최초 명세서 후보 5개·10개 전체 초안 비교

2026-11-24 · tune OA 4건 · [이슈 #345](https://github.com/merge-mates/patent-ai-workspace/issues/345)

후보는 각 신규성·진보성 판단 묶음의 **대응 방향 모델 입력에 넣는 최초 명세서 문단**이다. 저장 BM25 순위 앞 5개와 같은 순위의 앞 10개를 비교했다. 두 조건은 구조화 OA, 당시 청구항, 인용문헌 대비, 법률 근거, 명세서 본문과 다른 입력 경로를 공유했다. 후보 블록을 뺀 최초 방향 요청은 13묶음 모두 문자열 수준에서 일치했다.

생성은 Anthropic `claude-haiku-5-5` Medium, 조건명을 가린 평정은 Anthropic `claude-opus-5-5` Medium으로 실행했다. OA 네 건에서 조건별로 의견서·보정안 생성 8회와 논점·보정 평정 8회를 완료했다. 본실행은 사건·조건마다 한 번 생성하고 한 번 평정했다.

| 지표 | 5개 | 10개 |
|---|---:|---:|
| 의견서 직접·부분·누락 (각 37논점) | 6·13·18 | 5·13·19 |
| 실질 문언 변경 보정 | 7 | 9 |
| 명세서가 지지한 실질 보정 | 4/7 | 8/9 |
| 명세서가 지지했고 의견서와도 일치한 보정 | 2 | 3 |
| 보류 판단 묶음 | 2 | 1 |
| 생성 API 호출 | 32 | 35 |
| 생성 입력 / 출력 토큰 | 581,606 / 129,377 | 673,058 / 148,359 |

C01 제10항은 5개 조건에서 보류였고 10개 조건에서는 추가 문단 [0023]이 보정 근거로 쓰였다. 의견서도 같은 문언 변경을 설명했다. C03은 최초에 직접 응답 3→2였지만 별도 한 번의 반복에서는 1→3이었다. 반복의 5개 조건 제6항은 출력 형식 검사와 재호출에서 실패해 보류됐다. 반복 결과는 본실행 합계에 포함하지 않았다. 사람 판정 일치도는 미측정이다.

**후속 실험의 비교 기준은 명세서 문단 5개다.** 이 실험에서 추가한 방향 입력 블록은 아직 제품 기본 실행에 연결되지 않았다. 10개 조건에서 보정 지지 평정은 늘고 의견서 논점 대응은 늘지 않았다. 보정 근거가 부족한 묶음에서만 추가 문단을 전달하는 방식은 별도 검증 대상으로 남긴다.

## 재현

`PILOT`은 기존 로컬 실험 루트다. 아래 파일이 필요하다.

- `round1-spec-propagation/direction-payloads.jsonl`, `draft-comparison/<case>/common-input.json`
- `round2-routing/issues.jsonl`, `spec-retrieval/<case>/paragraphs.jsonl`

```sh
PILOT=work/e2e_2026-11-24_oa4
TOOLS=experiments/m3-i2-spec-before-direction-pilot
OUT="$PILOT/final-spec-cap/reproduction"
uv run python "$TOOLS/spec_cap_generate.py" "$PILOT" "$OUT"
# 아래 두 명령의 --live는 승인된 실데이터를 공식 Anthropic API로 전송한다.
uv run python "$TOOLS/spec_cap_generate.py" "$PILOT" "$OUT" --live
uv run python "$TOOLS/spec_cap_evaluate.py" "$PILOT" "$OUT" --live
uv run python "$TOOLS/spec_cap_summary.py" "$PILOT" "$OUT"
```

첫 실행은 외부 호출 없이 공통 입력·순위·설정을 준비한다. 평가 실행기의 기본 모드는 평가 입력을 생성한다. 저장된 결과 폴더에는 집계 실행기만 실행하면 된다. C03 반복에는 별도 출력 폴더와 `--case C03`을 사용한다. 실제 OA 원문·사건 번호·골드와 모델 원응답은 Git 제외 로컬 출력에 둔다.
