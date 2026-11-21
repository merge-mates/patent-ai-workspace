# API 명세 (v0)

화면과 서버가 이 문서만 보고 동시에 만든다. 요청·응답 스키마의 필드 이름·타입·필수 여부는 서버 구현(FastAPI)에서 정하고, OpenAPI 문서는 코드에서 자동으로 만든다. 화면의 TypeScript 타입도 그 OpenAPI에서 뽑는다. 생성한 OpenAPI는 `docs/api/openapi.yaml`에 커밋한다(손으로 고치지 않음). 서버가 생기기 전까지 화면은 가짜 결과 파일(`tests/fixtures/`)로 만든다. 결과 응답 본문 스키마는 [데이터 모델](../data-model.md) 4절의 결과 스키마를 그대로 쓴다.

## 1. 이름
| 이름 | 뜻 | 어디에 |
|---|---|---|
| 결과 스키마 | AI 결과 여섯 개 (OA 정리, 판단 단위, 대비표, 법률 근거 묶음, 대응 방향 후보, 사건 자료·보류 목록) | `core/schemas/` Pydantic |
| 요청·응답 스키마 | 엔드포인트마다 만드는 Pydantic 클래스 (Spring의 요청·응답 DTO). 결과 응답 스키마는 결과 스키마를 안에 담고 필드를 다시 베껴 쓰지 않는다 (예: `OAResultResponse { oa_id, run_id, status, result: OAResult }`) | API 쪽 Pydantic (`response_model`) |
| DB 모델 | 테이블 | SQLAlchemy (ORM 모델) |

FastAPI 관례대로 Pydantic 클래스는 스키마, SQLAlchemy 클래스는 모델이라 부른다. 그냥 "스키마"라고만 쓰지 않고 위 이름 중 하나로 쓴다. 도메인 모델과 나머지 열린 이름은 [데이터 모델](../data-model.md) 1절·6절.

## 2. 공통 규칙
- 로그인은 없다. DB에 기본 사용자 한 명을 두고 모든 요청은 그 사용자로 처리한다. `cases` 테이블에는 `user_id` 컬럼을 둔다.
- 결과 상태(확인됨 / 확인되지 않음 / 조회 범위 내 없음 / 충돌)는 200 응답 안의 `status`로 준다. HTTP 오류 코드는 요청이 잘못됐을 때만 쓴다.
- 응답 바깥 `status`는 `result.status.value`를 복사한다(기준은 result). `result.status`는 객체 `{value, reason, checked, searched_scope}`다.
- `status`·`origin` 값은 [데이터 모델](../data-model.md) 3절의 영어 코드(`confirmed`·`ai_generated` 등)를 쓴다. 화면에서 한국어로 보여 준다.
- 결과 엔드포인트는 `succeeded` 또는 `waiting_for_human`(사람 기다림) 실행이 낸 가장 최근 결과를 준다. 사람 기다림 중에도 그때까지의 정리를 볼 수 있다. 결과가 아직 없으면(실행 전·실행 중, 또는 가장 최근 실행이 failed·cancelled이고 앞에 보여 줄 실행이 없을 때) 404 `{code: "result_not_ready"}`다. 화면은 응답 `run_id`와 `latest_run`으로 이 경우들을 가른다. 실행이 끝났는데 목록이 비면 200 + 빈 목록 + `empty_reason`(해당 거절이유 없음 / 보류: 기다리는 자료)을 준다. 보류는 사건 자료·보류 목록(⑥)의 "보류한 작업"과 같은 항목을 가리킨다. 빈 목록을 이유 없이 돌려주지 않는다. F3·F4 결과(`units`·`comparisons`·`clarity-reviews`·`legal-evidence`·`directions`·`drafts`) 응답은 `{oa_id, run_id, result, empty_reason}`이고 `result`에 결과 스키마 목록(`drafts`는 `Drafts` 하나 또는 null)을 담는다. `run_id`는 OA 정리(`oa-result`)와 같은 실행이다. 단계를 넘겼으면 `empty_reason`이 `넘김: <이유>`다 (예: F2 `넘김: tool_missing: …`, 청구항 판을 못 찾은 F3·F4 `넘김: input_unverified: …`). `directions`는 `rank_notice`, `drafts`는 `held_units`·`legality_notice`를 같이 준다.
- 오류 본문은 한 형식이다: `{code, message}`. 오류에 따라 칸을 더 담을 수 있다 (예: 409 `document_already_exists`는 `case_id`·`oa_id`).
- 오래 걸리는 AI 실행은 만들기 → 상태 보기(폴링) → 결과 받기 순서다.
- 실행 취소(`POST /runs/{id}/cancel`): queued·waiting_for_human은 바로 `cancelled`로 답한다. running은 취소 표시만 하고 응답 `state`는 `running` 그대로이니, 화면은 폴링으로 `cancelled`를 확인한다.
- 실행 관련 오류: 409 `run_in_progress`(같은 OA에 진행 중인 실행이 있음), 409 `run_already_finished`(이미 끝난 실행을 취소), 500 `launch_failed`(실행을 시작하지 못함. 그 실행은 failed로 남는다), 404 `run_not_found`.
- 실행이 `failed`일 때 `error.code`는 `server_restarted`(서버가 다시 켜져 중단) · `step_failed`(단계 실패) · `oa_already_exists`(이미 올린 OA) · `max_steps`·`invalid_tool_choice`·`no_oa_result`(지휘가 끝내지 못함) · `result_save_failed`(결과 저장 실패) · `executor_crashed`(실행기가 예상 밖으로 죽음) · `launch_failed`(시작 실패) 중 하나다. `error.message`에는 어느 단계에서 어떤 종류로 실패했는지만 담고 예외 원문은 담지 않는다 (원문은 서버 로그). 서버는 실행을 한 번에 하나만 돌리고, 뒤에 온 실행은 `queued`로 기다린다.
- 평가(평가 세트 채점)는 API를 거치지 않고 스크립트가 `core/`를 직접 부른다.

## 3. 엔드포인트
결과와 실행은 사건 아래가 아니라 OA 아래에 둔다. 사건 하나에 OA가 여럿일 수 있고, 자동 조회의 "OA 시점까지만" 자르기도 OA마다 하기 때문이다.

### 사건과 자료
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/cases` | 첫 OA PDF 하나를 올려 PDF를 저장하고 사건·OA를 만든 뒤 실행 하나를 바로 시작한다. `{case_id, oa_id, run_id}`를 돌려준다. 실행 안에서 OA 읽기 → 자동 조회 + OA 시점 자르기 → 분석이 이어진다 |
| POST | `/cases/{id}/oas` | 같은 사건의 다음 OA를 올리고 실행을 시작한다. `{oa_id, run_id}`를 돌려준다 |
| GET | `/cases` | 사건 목록 |
| GET | `/cases/{id}` | 사건 보기 (OA 목록 포함). 묶기 결과가 저장된 뒤에는 이력 `events`(순서 `seq`), 청구항 판 `claim_versions`, OA마다 심사 대상 판 `examined_claim_version`도 준다 (저장 전에는 빈 목록·null). 이력·청구항 판은 원문이 있는 OA 중 가장 늦은 OA 시점까지 자르고 공개·등록공보 판은 뺀다 |
| GET | `/oas/{oa_id}` | OA 보기 (통지 정보, 원문 문서 ID, 가장 최근 실행 `latest_run`: run_id·state·current_step). 화면은 사건을 다시 열 때 이것으로 실행을 찾는다 |
| GET | `/cases/{id}/materials` | 사건 자료·보류 목록 (결과 스키마 ⑥) |
| POST | `/cases/{id}/documents` | 조회하지 못한 자료를 올린다 ("올려 주세요"에 답함). 폼으로 `file`(PDF)과 `what`(답하는 빠진 자료, `missing[].what` 글자 그대로)을 받고 `{case_id, document_id, result: CaseMaterials}`를 돌려준다. 그 빠진 자료와 그 자료를 기다리던 보류 작업이 빠진다. 오류: 404 `case_not_found`·`result_not_ready`(묶기 결과 전), 422 `missing_not_found`·`upload_not_asked`(직접 확인할 자료)·`empty_file`·`not_pdf`, 409 `document_already_exists`(같은 사건에 같은 파일, `case_id`) |
| GET | `/documents/{id}` | 원문과 쪽 |

### 실행
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/oas/{oa_id}/runs` | 지휘 에이전트를 끝까지 돌린다. 빠진 자료를 더 올렸거나 대응 방향을 바꿨을 때는 "다시 확인 필요"가 붙은 판단 단위만 다시 돌릴 수 있다 (사람이 정함, [데이터 모델](../data-model.md) 3절 규칙 2) |
| GET | `/runs/{id}` | 실행 상태 + "지금 하는 주요 작업" 한 줄 (세부 과정 중계 없음) |
| POST | `/runs/{id}/cancel` | 실행 취소 |

실행 상태 `state`: `queued`(대기) / `running`(실행 중) / `waiting_for_human`(사람 기다림: 확신 낮은 묶음에서 방향 고르기를 기다림) / `succeeded`(끝남) / `failed`(실패, 이유를 남김) / `cancelled`(취소). 실패를 succeeded로 돌려주지 않는다. 자동 조회의 진행·실패도 이 실행에 남는다. 화면은 `GET /runs/{id}`만 폴링한다. "사람 기다림"에서 방향을 고르면(`PUT /directions/{unit_id}/selection`) 기다리던 실행이 이어서 돈다. 이어 가는 방식은 지휘 에이전트 호출 이슈에서 정한다 (실행을 멈추지 않고 그 묶음만 보류하는 안도 그때 같이 본다).

### 결과 (OA 아래)
| 메서드 | 경로 | 결과 스키마 |
|---|---|---|
| GET | `/oas/{oa_id}/oa-result` | ① OA 정리 |
| GET | `/oas/{oa_id}/units` | ② 판단 단위 |
| GET | `/oas/{oa_id}/comparisons` | ③ 대비표 (진보성·신규성) |
| GET | `/oas/{oa_id}/clarity-reviews` | 명확성 문구 검토 (스키마는 F3 설계 때) |
| GET | `/oas/{oa_id}/legal-evidence` | ④ 법률 근거 묶음 (OA 흐름에서 지휘 에이전트가 자동으로 찾은 것) |
| GET | `/oas/{oa_id}/directions` | ⑤ 대응 방향 후보 |
| GET | `/oas/{oa_id}/drafts` | 의견서·보정 청구항 초안 + 초안 검사 결과 (스키마는 F4 설계 때) |
| GET | `/oas/{oa_id}/case-check` | 사건 전체 검사 (스키마는 F4 설계 때) |

### 사람이 하는 것
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| PUT | `/directions/{unit_id}/selection` | `unit_id`는 내용으로 정한 ID ([데이터 모델](../data-model.md) 4절 ②). 대응 방향을 후보 중에서 고르기. 고르지 않으면 1등 후보(origin = AI 기본값). 확신 "낮음" 묶음은 선택이 비어 있고(`null`), 사람이 고를 때까지 그 묶음 초안은 만들지 않는다(서버 코드로 막음). 이 PUT으로 저장한 선택은 1등 후보와 같아도 origin = 사람이 고름 |
| PATCH | `/drafts/{draft_id}` | 사람이 초안을 고친다. AI 원본 값은 남긴다. 중간 결과(F1·F2·F3)는 고치지 않는다 |

### 법률 질문 (자리만, 필드와 여러 번 묻고 답하는 방식은 F2 설계 때)
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/legal-chats` | 대화 만들기 |
| POST | `/legal-chats/{id}/messages` | 질문 보내기 |
| GET | `/legal-chats/{id}` | 대화 보기 |

### 그 밖
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/health` | 서버 확인 |
| (자리만) | 내려받기 | 시간이 남으면 |

## 4. 스키마가 바뀔 때
- 결과 스키마나 요청·응답 스키마가 바뀌는 PR은 본문에 "스키마 변경"을 적고 상대가 리뷰한다.
- breaking change(이름 바꾸기, 필드 빼기, 선택 필드를 필수로, 타입 바꾸기)는 PR 전에 말로 맞추고, fixture와 TS 타입을 같은 PR에서 고친다.
- 하위 호환 변경(선택 필드 더하기)은 미리 맞추지 않아도 된다. 화면에 보여야 하면 화면 이슈로 둔다.
- F2~F4 결과 스키마는 기능 설계 때 조금 바뀔 수 있다. 바뀌면 위 규칙대로 한다.

## 5. 응답 예시
필드의 기준은 결과 스키마와 서버 코드다. 여기서는 응답의 겉 구조만 보인다.

사건 만들기 (`POST /cases`):
```json
{"case_id": "c_1", "oa_id": "oa_1", "run_id": "r_1"}
```

실행 상태 (`GET /runs/{id}`):
```json
{"run_id": "r_1", "oa_id": "oa_1", "state": "succeeded", "current_step": "거절이유 정리 중", "waiting_for": null, "error": null, "skipped_steps": [{"step": "인용문헌 조회", "reason": "인용문헌 자료 없음"}], "warnings": [{"code": "step_skipped", "message": "인용문헌 조회 단계를 건너뜀: 인용문헌 자료 없음"}]}
```
`skipped_steps`·`warnings`는 넘긴 단계가 없으면 빈 목록이다. `POST /runs/{id}/cancel` 응답도 같은 모양이다.

결과 (`GET /oas/{oa_id}/oa-result`): 결과 스키마를 `result`에 그대로 담는다.
```json
{"oa_id": "oa_1", "run_id": "r_1", "status": "unverified", "result": {"...": "OAResult (데이터 모델 4절 ①)"}}
```

OA 보기 (`GET /oas/{oa_id}`):
```json
{"oa_id": "oa_1", "case_id": "c_1", "case_name": "출원번호 확인 전", "document_id": "doc_1", "latest_run": {"run_id": "r_1", "state": "queued", "current_step": null}, "dispatch_number": null}
```

오류:
```json
{"code": "oa_not_found", "message": "OA를 찾을 수 없습니다"}
```

같은 파일을 다시 올렸을 때 (`POST /cases`, 409):
```json
{"code": "document_already_exists", "message": "이미 올린 파일입니다", "case_id": "c_1", "oa_id": "oa_1"}
```
`POST /cases/{id}/oas`도 같은 사건 안에서 같은 파일이면 409이고, `case_id`는 요청한 사건, `oa_id`는 그 사건의 기존 OA다 (다른 사건에 있는 파일은 다음 OA로 올릴 수 있다).
