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
- 결과 엔드포인트는 `succeeded` 또는 `waiting_for_human`(사람 기다림) 실행이 낸 가장 최근 결과를 준다. 사람 기다림 중에도 그때까지의 정리를 볼 수 있다. 결과가 아직 없으면(실행 전·실행 중, 또는 가장 최근 실행이 failed·cancelled이고 앞에 보여 줄 실행이 없을 때) 404 `{code: "result_not_ready"}`다. 화면은 응답 `run_id`와 `latest_run`으로 이 경우들을 가른다. 실행이 끝났는데 목록이 비면 200 + 빈 목록 + `empty_reason`(해당 거절이유 없음 / 보류: 기다리는 자료)을 준다. 보류는 사건 자료·보류 목록(⑥)의 "보류한 작업"과 같은 항목을 가리킨다. 빈 목록을 이유 없이 돌려주지 않는다. F3·F4 결과(`units`·`comparisons`·`clarity-reviews`·`legal-evidence`·`directions`·`drafts`) 응답은 `{oa_id, run_id, result, empty_reason}`이고 `result`에 결과 스키마 목록(`drafts`는 `Drafts` 하나 또는 null)을 담는다. `run_id`는 OA 정리(`oa-result`)와 같은 실행이다. 단계를 넘겼으면 `empty_reason`이 `넘김: <이유>`다 (예: 청구항 판을 못 찾은 F3와 그 뒤 F2·F4 `넘김: input_unverified: …`). 저장한 결과를 지금 모델로 못 읽으면(칸이 바뀐 옛 줄) `확인되지 않음: 저장된 결과를 읽지 못함 (다시 실행 필요)`, 사람 확인을 기다리느라 그 단계 전에 멈췄으면 `보류: 사람 확인을 기다림 (<기다리는 것>)`, 이유를 모르면 `확인되지 않음: 이 실행에 결과가 없음`이다. `directions`는 `rank_notice`, `drafts`는 `held_units`·`legality_notice`를 같이 준다.
- 오류 본문은 한 형식이다: `{code, message}`. 오류에 따라 칸을 더 담을 수 있다 (예: 409 `document_already_exists`는 `case_id`·`oa_id`).
- 오래 걸리는 AI 실행은 만들기 → 상태 보기(폴링) → 결과 받기 순서다.
- 실행 취소(`POST /runs/{id}/cancel`): queued·waiting_for_human은 바로 `cancelled`로 답한다. running은 취소 표시만 하고 응답 `state`는 `running` 그대로이니, 화면은 폴링으로 `cancelled`를 확인한다.
- 실행 관련 오류: 409 `run_in_progress`(같은 OA에 진행 중인 실행이 있음), 409 `run_already_finished`(이미 끝난 실행을 취소), 500 `launch_failed`(실행을 시작하지 못함. 그 실행은 failed로 남는다), 404 `run_not_found`.
- 실행이 `failed`일 때 `error.code`는 `server_restarted`(서버가 다시 켜져 중단) · `step_failed`(단계 실패) · `oa_already_exists`(이미 올린 OA) · `max_steps`·`invalid_tool_choice`·`no_oa_result`(지휘가 끝내지 못함) · `result_save_failed`(결과 저장 실패) · `record_failed`(실행 기록 저장 실패) · `executor_crashed`(실행기가 예상 밖으로 죽음) · `launch_failed`(시작 실패) 중 하나다. `error.message`에는 어느 단계에서 어떤 종류로 실패했는지만 담고 예외 원문은 담지 않는다 (원문은 서버 로그). 서버는 실행을 한 번에 하나만 돌리고, 뒤에 온 실행은 `queued`로 기다린다.
- 평가(평가 세트 채점)는 API를 거치지 않고 스크립트가 `core/`를 직접 부른다.

## 3. 엔드포인트
결과와 실행은 사건 아래가 아니라 OA 아래에 둔다. 사건 하나에 OA가 여럿일 수 있고, 자동 조회의 "OA 시점까지만" 자르기도 OA마다 하기 때문이다.

### 사건과 자료
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/cases` | 첫 OA PDF 하나를 올려 PDF를 저장하고 사건·OA를 만든 뒤 실행 하나를 바로 시작한다. `{case_id, oa_id, run_id}`를 돌려준다. 실행 안에서 OA 읽기 → 자동 조회 + OA 시점 자르기 → 분석이 이어진다 |
| POST | `/cases/{id}/oas` | 같은 사건의 다음 OA를 올리고 실행을 시작한다. `{oa_id, run_id}`를 돌려준다 |
| GET | `/cases` | 사건 목록 |
| GET | `/cases/{id}` | 사건 보기 (OA 목록 포함). 같은 출원번호 사건에 합쳐진 임시 사건이면 `merged_into_case_id`에 합친 사건 id(그때 `oas`는 빈 목록, 사건 목록에서는 숨김. 그 사건에 `POST /cases/{id}/oas`를 하면 합친 사건에 붙는다). 묶기 결과가 저장된 뒤에는 이력 `events`(순서 `seq`), 청구항 판 `claim_versions`, OA마다 심사 대상 판 `examined_claim_version`도 준다 (저장 전에는 빈 목록·null). 이력·청구항 판은 원문이 있는 OA 중 가장 늦은 OA 시점까지 자르고 공개·등록공보 판은 뺀다 |
| GET | `/oas/{oa_id}` | OA 보기 (통지 정보, 원문 문서 ID, 가장 최근 실행 `latest_run`: run_id·state·current_step). 화면은 사건을 다시 열 때 이것으로 실행을 찾는다 |
| GET | `/cases/{id}/materials` | 사건 자료·보류 목록 (결과 스키마 ⑥). 실행이 끝나면 만든다. 아직 없으면 404 `result_not_ready`, 출원번호를 모르면(실행 전·못 읽음·같은 출원번호 사건에 같은 파일이 이미 있음) 메시지에 그 이유, 합쳐진 임시 사건이면 합친 사건 id |
| POST | `/cases/{id}/documents` | 조회하지 못한 자료를 올린다 ("올려 주세요"에 답함). 폼으로 `file`(PDF)과 `what`(답하는 빠진 자료, `missing[].what` 글자 그대로)을 받고 `{case_id, document_id, result: CaseMaterials}`를 돌려준다. 그 빠진 자료와 그 자료를 기다리던 보류 작업이 빠진다. 오류: 404 `case_not_found`·`result_not_ready`(묶기 결과 전), 422 `missing_not_found`·`upload_not_asked`(직접 확인할 자료)·`empty_file`·`not_pdf`, 409 `document_already_exists`(같은 사건에 같은 파일, `case_id`) |
| GET | `/documents/{id}` | 원문과 쪽: 올린 문서의 쪽 글자 `PageText`(쪽마다 `page`·`text`·`status`·`tables`, 문서 전체 `status`). 요청 때 원본 PDF에서 뽑는다. 원본 파일을 못 읽으면 200 + `pages: []` + `status` 확인되지 않음(`lookup_failed`). 오류: 404 `document_not_found` |

### 실행
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/oas/{oa_id}/runs` | 지휘 에이전트를 끝까지 돌린다. 빠진 자료를 더 올렸거나 대응 방향을 바꿨을 때는 "다시 확인 필요"가 붙은 판단 단위만 다시 돌릴 수 있다 (사람이 정함, [데이터 모델](../data-model.md) 3절 규칙 2) |
| GET | `/runs/{id}` | 실행 상태 + "지금 하는 주요 작업" 한 줄 (세부 과정 중계 없음). `case_id`는 그 OA가 지금 속한 사건이다: F1이 읽은 출원번호의 사건이 이미 있으면 실행이 끝날 때 OA를 그 사건의 다음 OA로 옮기므로 합친 사건 id가 된다 |
| POST | `/runs/{id}/cancel` | 실행 취소 |

실행 상태 `state`: `queued`(대기) / `running`(실행 중) / `waiting_for_human`(사람 기다림: OA 번호(출원번호·발송번호)를 못 읽어 사람 입력을 기다림) / `succeeded`(끝남) / `failed`(실패, 이유를 남김) / `cancelled`(취소). 실패를 succeeded로 돌려주지 않는다. 자동 조회의 진행·실패도 이 실행에 남는다. 화면은 `GET /runs/{id}`만 폴링한다. `waiting_for` 값은 `application_number`·`dispatch_number` 둘뿐이다. 번호를 넣으면(`PATCH /cases/{id}`·`PATCH /oas/{id}`) 같은 실행이 `waiting_for_human → running`으로 이어 돈다. 체크포인터 없이, 그 실행이 저장해 둔 OA 정리에 사람이 넣은 번호를 덮어 `check_oa`부터 돈다 (OA 글자 읽기는 다시 하지만 F1 모델은 다시 부르지 않는다). 방향 고르기는 실행을 멈추지 않는다: 실행은 `succeeded`로 끝나고 확신 낮은 묶음만 선택 `null` + 초안 보류이며, 사람이 고르면(`PUT /directions/{unit_id}/selection`) 그 OA에 작은 실행을 새로 만든다.

### 결과 (OA 아래)
| 메서드 | 경로 | 결과 스키마 |
|---|---|---|
| GET | `/oas/{oa_id}/oa-result` | ① OA 정리 |
| GET | `/oas/{oa_id}/units` | ② 판단 단위 |
| GET | `/oas/{oa_id}/comparisons` | ③ 대비표 (진보성·신규성) |
| GET | `/oas/{oa_id}/clarity-reviews` | 명확성 문구 검토 (스키마는 F3 설계 때) |
| GET | `/oas/{oa_id}/legal-evidence` | ④ 법률 근거 묶음 (OA 흐름에서 지휘 에이전트가 자동으로 찾은 것) |
| GET | `/oas/{oa_id}/directions` | ⑤ 대응 방향 후보 |
| GET | `/oas/{oa_id}/drafts` | 의견서·보정 청구항 초안. 초안 검사 결과(누락·번호 불일치)는 #40 전까지 응답에 없다 |
| GET | `/oas/{oa_id}/case-check` | 사건 전체 검사. 응답 `{oa_id, run_id, items[{name, result: ok·warn·fail, detail}], unsupported_rejections}` (OA 정리와 같은 실행). 지금 검사하는 규칙은 지원 안 하는 거절이유·두 묶음이 같은 청구항을 고친 것 둘이고, 아직 검사하지 않는 규칙은 `ok`로 두지 않고 `warn` + `확인되지 않음`이다. 칸은 F4 설계(#39)에서 정해지면 바꾼다. 오류: 404 `oa_not_found`·`result_not_ready` |

### 사람이 하는 것
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| PUT | `/directions/{unit_id}/selection` | `unit_id`는 내용으로 정한 ID ([데이터 모델](../data-model.md) 4절 ②). 대응 방향을 후보 중에서 고르거나 직접 쓰기. 본문은 `{candidate_id}` 또는 `{written_direction}` 중 하나. 응답은 `{unit_id, run_id, selection}`이고 `run_id`는 새로 만든 작은 실행이다(화면은 그 `run_id`를 폴링). 작은 실행은 앞 실행의 OA 정리·F3·F2를 그대로 옮기고 F4 방향 후보도 그대로 둔 채 선택만 바꿔 의견서·보정 초안을 다시 만든다. 직접 쓴 묶음은 AI가 초안을 만들지 않고 보류한다("사람이 쓴 방향", origin = `human_written`). 오류: 404 `oa_not_found`·`unit_not_found`, 404 `result_not_ready`, 409 `run_in_progress`(그 OA에 진행 중 실행), 422 `candidate_not_found`·`invalid_selection`(빈 글 등). 고르지 않으면 1등 후보(origin = AI 기본값). 확신 "낮음" 묶음은 선택이 비어 있고(`null`), 사람이 고를 때까지 그 묶음 초안은 만들지 않는다(서버 코드로 막음). 이 PUT으로 저장한 선택은 1등 후보와 같아도 origin = 사람이 고름 |
| PATCH | `/cases/{id}` | 본문 `{application_number}`. 그 사건 OA 중 출원번호를 기다리는(`waiting_for: application_number`) 실행에 사람이 읽은 출원번호를 넣고 그 실행을 이어 돌린다. 하이픈은 있어도 되고 숫자로 맞춘다. 그 실행은 바로 `waiting_for_human → queued`로 바뀌고(조건부: 그 사이 다른 요청이 가져갔으면 409 `not_waiting`), 실행기가 잡으면 `running`으로 이어 돈다. 응답 `{case_id, oa_id, run_id}` (화면은 그 run_id를 폴링). 사람이 넣은 값은 `human_inputs` 표에 남기고, OA 정리의 그 칸은 status 확인됨 + `checked: "사람이 직접 입력함 (원문 대조 아님)"`으로 AI가 읽은 값과 구분한다. 오류: 404 `case_not_found`, 409 `not_waiting`(출원번호를 기다리는 실행 없음), 422 `invalid_application_number`(출원번호 꼴 아님), 500 `human_input_not_saved`(번호 기록을 못 남김: 실행은 `queued`에서 다시 `waiting_for_human`으로 되돌아가니 다시 넣으면 된다) |
| PATCH | `/oas/{id}` | 본문 `{dispatch_number}`. 발송번호를 기다리는 실행에 넣고 이어 돌린다. 응답·남기는 방식은 위와 같다. 오류: 404 `oa_not_found`, 409 `not_waiting`, 422 `invalid_dispatch_number`, 500 `human_input_not_saved` |
| PUT | `/oas/{id}/oa-result/confirmation` | 정리 결과 "맞아요": 사람이 본 OA 정리를 확인했다고 남긴다. 본문 `{run_id}` (화면에 보이던 정리를 낸 실행, 필수. 없으면 422). 그 `run_id`가 지금 보이는 정리의 실행과 다르면(그 사이 다시 돌림) 확인을 남기지 않고 409 `stale_result`. 그 OA의 실행이 출원번호·발송번호를 기다리는 동안은 409 `waiting_for_number`(번호를 넣으면 같은 `run_id`로 정리가 바뀌어서. 다른 사람 기다림은 막지 않는다). 응답 `{oa_id, run_id, confirmed_at}`. 다시 보내면 시각만 새로 남는다. 다른 실행의 정리가 보이게 되면(다시 돌림) 확인은 그 실행 것이 아니라 비어 보인다. 오류: 404 `oa_not_found`·`result_not_ready`, 409 `stale_result`·`waiting_for_number`, 422 `validation_error`(본문·`run_id` 없음) |
| GET | `/oas/{id}/oa-result/confirmation` | 지금 보이는 OA 정리를 사람이 확인했는지. `{oa_id, run_id, confirmed_at}`, 확인 전이면 `confirmed_at: null`. 오류: 404 `oa_not_found`·`result_not_ready` |
| PATCH | `/drafts/{draft_id}` | 사람이 초안을 고친다. 본문은 `{section, text}`(의견서 칸 key) 또는 `{claim, text}`(보정 청구항 번호) 중 하나. AI 원문 `ai_text`는 그대로 두고 `human_text`·`origin = human_edited`만 바꾼다. AI 원문과 같은 글을 보내면 고친 것을 되돌린다. 고치는 초안은 지금 보이는 실행(OA 정리와 같은 실행)의 초안이고, 다시 열면(`GET /oas/{oa_id}/drafts`) 고친 글이 나온다. 응답은 고친 `Drafts` 전체. 중간 결과(F1·F2·F3)는 고치지 않는다. 오류: 404 `draft_not_found`(없는 초안·결과 전·F4 넘김), 409 `run_in_progress`(그 OA에 진행 중 실행: 끝나면 새 초안이 보여 고친 글이 가려지므로 막음), 422 `claim_not_editable`(없는 번호·보류된 청구항)·`invalid_draft_edit`(칸·번호 중 하나가 아님, 없는 칸, 빈 글)·`validation_error`(`text` 없음) |

### 법률 질문 (사건 없이도 여러 번 묻고 답한다, 이슈 #29)
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/legal-chats` | 대화 만들기. 본문 `{case_id?}`(없어도 됨). 201 `{chat_id}`. 오류: 404 `case_not_found` |
| POST | `/legal-chats/{id}/messages` | 질문 보내기. 본문 `{text, as_of?, source_kinds?}`. `as_of`·`source_kinds`는 빠지면 앞 질문 것을 물려받고(첫 질문은 현행·전부), `as_of: null`은 현행으로 덮고, `source_kinds: []`는 전부다. 200 `{chat_id, no, scope_changed, result}`이고 `result`는 법률 근거 묶음(`LegalEvidenceBundle`)이다. `scope_changed`는 앞 질문과 시점 또는 자료 유형이 달라졌는지다. 조문 일부만 찾으면 못 찾은 조문도 근거 없는 주장으로 남고 묶음 status는 그중 가장 나쁜 값이다. 글에 조문 번호가 있으면 그 조문을, 없으면 BM25로 찾은 조문을 근거로 준다(심사기준·판례·심결은 아직 검색 전이라 `body_missing`으로 기록만). 법령 색인을 못 읽으면 200 + 주장 없는 묶음 + `unverified(body_missing)`다. 오류: 404 `chat_not_found`, 422 `invalid_question`(빈 글·잘못된 값·JSON 객체 아님), 500 `chat_corrupt`(저장된 대화를 못 읽음) |
| GET | `/legal-chats/{id}` | 대화 보기. `{chat_id, case_id, created_at, turns: [{no, question, scope_changed, created_at, result}], prior_evidence}`. 오류: 404 `chat_not_found`, 500 `chat_corrupt`(저장된 턴을 스키마대로 못 읽음, 빈 대화로 돌려주지 않음) |

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
{"run_id": "r_1", "oa_id": "oa_1", "state": "succeeded", "current_step": "결과 저장 중", "waiting_for": null, "error": null, "skipped_steps": [{"step": "run_f3", "reason": "input_unverified: OA 당시 청구항·명세서 글자를 찾지 못함"}, {"step": "run_f2", "reason": "input_unverified: 앞 단계인 청구항–인용발명 대비 결과가 없음"}, {"step": "run_f4", "reason": "input_unverified: 앞 단계인 청구항–인용발명 대비 결과가 없음"}], "warnings": [{"code": "step_skipped", "message": "run_f3 단계를 건너뜀: input_unverified: OA 당시 청구항·명세서 글자를 찾지 못함"}, {"code": "step_skipped", "message": "run_f2 단계를 건너뜀: input_unverified: 앞 단계인 청구항–인용발명 대비 결과가 없음"}, {"code": "step_skipped", "message": "run_f4 단계를 건너뜀: input_unverified: 앞 단계인 청구항–인용발명 대비 결과가 없음"}]}
```
`skipped_steps`·`warnings`는 넘긴 단계가 없으면 빈 목록이다. `step`은 지휘 도구 이름(`read_oa`·`run_f3`·`run_f2`·`run_f4`)이고, `reason`은 앞머리 코드(`input_unverified`·`tool_missing`) 뒤에 사람이 읽는 이유 글이 붙는다. 끝난 실행의 `current_step`은 마지막으로 기록된 단계 글(F4 뒤면 "결과 저장 중")이 남는다. `POST /runs/{id}/cancel` 응답도 같은 모양이다.

결과 (`GET /oas/{oa_id}/oa-result`): 결과 스키마를 `result`에 그대로 담는다.
```json
{"oa_id": "oa_1", "run_id": "r_1", "status": "unverified", "result": {"...": "OAResult (데이터 모델 4절 ①)"}}
```

OA 보기 (`GET /oas/{oa_id}`):
```json
{"oa_id": "oa_1", "case_id": "c_1", "case_name": "출원번호 확인 전", "document_id": "doc_1", "latest_run": {"run_id": "r_1", "state": "queued", "current_step": null}, "dispatch_number": null}
```

법률 질문 답 (`POST /legal-chats/{id}/messages`):
```json
{"chat_id": "lc_1", "no": 2, "scope_changed": true, "result": {"...": "LegalEvidenceBundle (데이터 모델 4절 ④)"}}
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
