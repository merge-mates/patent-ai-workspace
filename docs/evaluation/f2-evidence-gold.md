# F2 근거 검토 정답 (초안)

- 상태: 초안, 은진 검수 전 (#35). 채점기는 #29가 만든다. 여기에는 정의만 둔다.
- 근거: [F2 requirements](../features/F2/requirements.md) 합격 기준 6·9·10과 열린 질문 5, [F2 design](../features/F2/design.md) 7-1, 결과 스키마 `LegalEvidenceBundle` (`src/patent_ai/core/schemas/legal_evidence.py`).
- 파일 위치·버전은 [eval/GUIDE.md](../../eval/GUIDE.md). 형식 검사는 `eval/f2/gold.py`. 아래 예시 번호는 모두 만든 값이다.

## 1. 무엇을 재나
- 실제 질문: F2 조사(research)가 OA 거절이유 질문에 맞는 조문을 맞는 판본·위치로 찾아 내는가.
- 오류 주입: 근거 검토(evidence review)가 겉으로 멀쩡한 잘못된 근거를 잡고(탐지), 고칠 정답이 있으면 고치는가(고침).
- 지킬 선 (design 7-1): 없는 출처를 근거로 낸 답 0건 = `nonexistent_source` 탐지율 1.0.

## 2. 판정 단위
- 한 줄 = 사례 하나. 실제 질문은 OA 거절이유 하나, 주입은 망가뜨린 근거 하나(주장 하나 × 근거 하나).
- 점수는 사례 → OA 한 통 평균 → 세트 평균. 주입 사례는 `base_case_id`의 OA로 모은다 (바탕이 없으면 그 사례 자체가 한 통).

## 3. 파일 꼴
`data/goldsets/<세트>/f2/evidence_cases.jsonl`, 한 줄이 JSON 하나. `kind`로 둘로 나뉘고 모르는 칸은 거부한다.

공통 칸: `gold_version`(정수, VERSION과 같아야 함), `case_id`(비지 않음, 파일 안에서 겹치지 않음), `reviewed`(`by`·`date`, 검수 전이면 둘 다 null).

### 3-1. 실제 질문 `kind: "real"`
```json
{"kind": "real", "gold_version": 2, "case_id": "real:900000000000001:r1",
 "reviewed": {"by": null, "date": null},
 "oa_id": "900000000000001", "rejection": 1,
 "question": {"text": "가짜 질문: 가짜 요건은 무엇인가", "source": "oa_rejection",
              "as_of": "2020-01-01", "as_of_source": "oa_dispatch_date",
              "source_kinds": ["statute"], "article_refs": []},
 "expect_sources": [{"source_kind": "statute", "identifier": "가짜법 제1조제2항",
                     "document_id": "가짜법_000001_20200101", "loc": 100200,
                     "edition_status": "confirmed"}]}
```
- `question`은 core의 `LegalQuestion` 그대로다. `source`는 `oa_rejection`, `as_of`는 꼭 있다.
- `expect_sources`는 1개 이상. `document_id`는 판본 문서 ID(색인 `doc_id`), `loc`은 조문 6자리 위치 번호(모르면 null), `edition_status`는 `confirmed` / `unverified`.

### 3-2. 오류 주입 `kind: "injected"`
```json
{"kind": "injected", "gold_version": 2, "case_id": "inject:other_edition_asserted:1",
 "reviewed": {"by": null, "date": null},
 "error": "other_edition_asserted", "base_case_id": "real:900000000000001:r1",
 "bundle": {"...": "검토 전 LegalEvidenceBundle (review 없음, 주장에 needs_human_review)"},
 "target_claim": 1, "target_source": 0,
 "fix": {"document_id": "가짜법_000001_20180101"}}
```
- `error` 다섯 가지: `nonexistent_source`(없는 출처) / `claim_text_mismatch`(주장–원문 불일치) / `other_edition_asserted`(다른 시점 판본을 적용으로 단정) / `summary_as_full`(요지만 보고 전문이라 씀) / `old_deadline_as_current`(개정 전 기한을 현행처럼).
- `bundle`은 core `LegalEvidenceBundle` 그대로, 근거 검토 전 모양이다. `target_claim`은 `claims[].no`, `target_source`는 그 주장 `sources`의 순번(0부터).
- 주입한 근거는 겉으로 멀쩡해야 하므로 target 근거 status는 `confirmed`다.
- `fix`: `identifier`, `document_id`, `text_kind`, `raw_text_contains` 중 하나 이상을 채운다. 칸이 null이면 "그 칸은 안 따짐". `fix` 자체가 null이면 고칠 정답이 없다 (빼거나 "확인 필요"로 두면 됨).
- 종류별 일관성 (형식 검사가 본다):

| error | 조건 |
|---|---|
| `nonexistent_source`, `claim_text_mismatch` | `fix`는 null |
| `summary_as_full` | target 근거가 판례·심결이고 `text_kind=full`, `fix.text_kind=summary` |
| `old_deadline_as_current` | `bundle.question.as_of`가 null(현행 질문), `fix.document_id`·`fix.raw_text_contains` 둘 다 있음 |
| `other_edition_asserted` | `fix.document_id`가 있고 target 근거의 `evidence.document_id`와 다름 |

## 4. 만드는 법
- 외부 모델 호출 없이 `eval/f2/make_cases.py`가 tune 세트의 `law_gold`와 법령·판례 원문에서 만든다. 같은 입력이면 같은 바이트가 나온다.
- 실제 질문: `law_gold`의 거절이유 줄 중 판본이 확인된 조문 줄이고, 정답 판이 OA 발송일에 시행 중인 줄만. 뺀 줄은 경고로 남긴다.
- 오류 주입 5종: 실제 질문의 맞는 근거를 코드로 망가뜨린다. 종류마다 4개. 없는 출처·주장 불일치·다른 판은 실제 질문이 넉넉하면 종류마다 다른 바탕 4개를 쓴다.
  - 없는 출처: 그 법의 어느 판에도 없던 가지 조 번호 (지워진 조문 번호도 피함).
  - 다른 판: 같은 위치가 있는 판 중 발송일에 시행 중이 아닌 판만 고른다.
- 기한 정답(`old_deadline_as_current`)은 공식 법령 원문의 판별 글에서만 뽑는다. 글에서 판별되지 않으면 그 사례를 빼지 않고 스크립트 전체가 멈춘다 (종류마다 정확히 4개).
- VERSION이 오르면 스크립트로 다시 만든다. 사람 검수(`reviewed`)는 사람이 본 줄에만 남긴다 (11/22 판은 Claude가 원문과 자동 대조만 했고 `reviewed`는 비어 있다).

## 5. 채점 정의 (채점기는 #29)
실제 질문 사례마다:
- 출처 존재율: 기대 근거 중 `identifier`가 같은 근거가 결과에 있는 비율.
- 위치 일치율: 그 근거의 `loc`이 같은 비율 (`loc`이 null인 기대는 분모에서 뺌).
- 판본 일치율: 그 근거의 `document_id`가 같은 비율.
- 뒷받침 판정 정확도: 실제 질문의 주장은 `supported`가 정답이다. 근거 검토가 `supported`로 낸 주장의 비율.

주입 사례마다:
- 잡음: target 주장의 `review.verdict`가 `supported`가 아니다, 또는 target 근거 status가 `confirmed`가 아니다, 또는 target 근거가 빠졌다, 또는 주장 status가 `confirmed`가 아니다. 넷 중 하나면 잡은 것이다.
- 고침: 잡았고, `fix`가 있고, 그 주장에 `fix`의 null 아닌 칸이 모두 맞는 `confirmed` 근거가 있다. `fix`가 null인 사례는 고친 비율 분모에서 뺀다.
- 종류별 탐지율·고친 비율을 따로 낸다.
- `review`가 null인 채로 나온 주장(검토를 안 함)은 그것만으로 잡은 것이 아니다. 위 넷 중 다른 하나에 걸릴 때만 잡은 것이다.

글자 비교: `identifier`·`location`은 공백을 모두 지운 뒤 비교한다 ("제29조 제2항" = "제29조제2항"). 조문 표기의 그 밖의 차이(예: "29조2항")는 다른 것으로 본다.

지킬 선 (requirements 합격 기준 10, design 7-1). 실제 질문·주입 사례 모두의 결과 묶음에서 `status`가 `confirmed`인 근거를 하나씩 센다. `unverified`·`not_found_in_scope` 근거는 확인 못 했다고 드러낸 것이라 세지 않는다. 세트 전체 합이 둘 다 0이어야 한다.
- **없는 출처 0건:** 법령 근거는 `evidence.chunk_id`가 그 `index_version` 색인에 있고, 그 조각의 `doc_id`가 `evidence.document_id`와 같아야 한다. 판례·심결 근거는 `document_id`가 받은 원문(판례 일련번호·심판번호)에 있어야 한다. 아니면 1건. 주입 `nonexistent_source`의 target 근거가 `confirmed`로 남으면 여기서도 1건이라, 이 선은 그 종류 탐지율 1.0을 포함한다. 6절 2번처럼 새로 붙은 틀린 근거도 여기서 센다.
- **확인하지 않은 원문 위치 0건:** 위 조각(판례면 원문)이 있는 근거 가운데, `evidence.raw_text`가 그 조각 글 안에 그대로(공백 정리 뒤) 들어 있지 않거나, `evidence.location`이 그 조각 위치 표기와 다르면 1건. 판례·심결은 `text_kind`에 맞는 칸(요지 = 판결요지, 전문 = 판례내용)에 `raw_text`가 있어야 한다. 그래서 주입 `summary_as_full`의 target 근거가 `confirmed`로 남으면 여기서 1건이다.

세트 크기 기준: 사례 합계 20개 이상, 오류 종류마다 1개 이상 (`check_set_size`).

## 6. 애매한 경우
1. 주장이 둘로 쪼개져 나오면: target 근거가 들어 있는 주장만 본다. 근거가 두 주장에 나뉘면 한 곳이라도 잡았으면 잡은 것이다.
2. 근거가 더 붙으면: 맞는 근거가 target 주장에 있으면 더 붙은 근거는 감점하지 않는다. 틀린 근거가 새로 붙은 것은 이 점수가 아니라 "없는 출처 0건" 선에서 본다.
3. 같은 조문의 다른 항 위치: `loc`이 다르면 위치 불일치다 (판본 일치는 따로 셈).
4. target 근거를 빼고 새 근거로 바꿔 낸 경우: 빠진 것으로 보아 잡은 것이다. 고침은 새 근거가 `fix`를 만족할 때만.

## 7. 심사기준·판례 검색 정답
11/22 정함: tune 30통에서 심사기준을 언급한 OA는 1통, 판례를 언급한 OA는 0통, 의견서 30통은 모두 0이다. `law-idx-v2`는 조문만 있다 (심사기준·판례 조각은 #24 `law-idx-v3`).
- M3에는 심사기준·판례 검색 점수를 재지 않는다 ([requirements](../features/F2/requirements.md) 합격 기준 9의 그 줄은 skipped).
- 남은 1줄은 #24 색인이 생겨 조각 위치가 정해지면 `law_gold`에 넣는다.
- 사람이 고른 정답은 만들지 않는다.

## 8. 대비(F3) 정답
대비 정답은 새로 만들지 않고 `retrieval/cite_gold.jsonl`(tune v2 105줄, 한국·미국 인용, 심사관이 짚은 식별번호를 대리 정답, `search_v0` 사람 검수본)을 쓴다.
- 판정 단위 = 거절이유 × 청구항 × 인용문헌 한 줄, 점수는 OA 한 통으로 모은다 ([search-gold.md](search-gold.md)).
- F3 사람 검수는 #225 7번(재아).
