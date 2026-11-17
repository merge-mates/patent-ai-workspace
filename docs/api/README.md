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
- 오류 본문은 한 형식이다: `{code, message}`.
- 오래 걸리는 AI 실행은 만들기 → 상태 보기(폴링) → 결과 받기 순서다.
- 평가(평가 세트 채점)는 API를 거치지 않고 스크립트가 `core/`를 직접 부른다.

## 3. 엔드포인트
결과와 실행은 사건 아래가 아니라 OA 아래에 둔다. 사건 하나에 OA가 여럿일 수 있고, 자동 조회의 "OA 시점까지만" 자르기도 OA마다 하기 때문이다.

### 사건과 자료
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/cases` | 첫 OA PDF 하나를 올려 사건과 OA를 만들고 자동 조회를 시작한다 |
| POST | `/cases/{id}/oas` | 같은 사건의 다음 OA를 올린다 |
| GET | `/cases` | 사건 목록 |
| GET | `/cases/{id}` | 사건 보기 (OA 목록 포함) |
| GET | `/oas/{oa_id}` | OA 보기 (통지 정보, 원문 문서 ID) |
| GET | `/cases/{id}/materials` | 사건 자료·보류 목록 (결과 스키마 ⑥) |
| POST | `/cases/{id}/documents` | 조회하지 못한 자료를 올린다 ("올려 주세요"에 답함) |
| GET | `/documents/{id}` | 원문과 쪽 |

### 실행
| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/oas/{oa_id}/runs` | 지휘 에이전트를 끝까지 돌린다. 빠진 자료를 더 올렸거나 대응 방향을 바꿨을 때는 "다시 확인 필요"가 붙은 판단 단위만 다시 돌릴 수 있다 (사람이 정함, [데이터 모델](../data-model.md) 3절 규칙 2) |
| GET | `/runs/{id}` | 실행 상태 + "지금 하는 주요 작업" 한 줄 (세부 과정 중계 없음) |
| POST | `/runs/{id}/cancel` | 실행 취소 |

실행 상태 값: 대기 / 실행 중 / 사람 기다림 (확신 낮은 묶음에서 방향 고르기를 기다림) / 끝남 / 실패 (이유를 남김) / 취소. 실패를 끝남으로 돌려주지 않는다. "사람 기다림"에서 방향을 고르면(`PUT /directions/{unit_id}/selection`) 기다리던 실행이 이어서 돈다. 이어 가는 방식은 지휘 에이전트 호출 이슈에서 정한다.

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
| PUT | `/directions/{unit_id}/selection` | 대응 방향을 후보 중에서 고르기. 고르지 않으면 1등 후보(AI 기본값) |
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

실행 상태 (`GET /runs/{id}`):
```json
{"run_id": "r_1", "oa_id": "oa_1", "state": "실행 중", "current_step": "인용문헌 2건 조회 중", "error": null}
```

결과 (`GET /oas/{oa_id}/oa-result`): 결과 스키마를 `result`에 그대로 담는다.
```json
{"oa_id": "oa_1", "run_id": "r_1", "status": "확인되지 않음", "result": {"...": "OAResult (데이터 모델 4절 ①)"}}
```

오류:
```json
{"code": "oa_not_found", "message": "OA를 찾을 수 없습니다"}
```
