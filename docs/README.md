# 문서 지도

## 지금
<!-- 프로젝트 전체 위치만 3줄. 기능 진행은 각 features/<기능>/tasks.md에. 결정이 나는 PR에서만 고친다. -->
- 단계: M2 걷는 뼈대(~11/21, F1~F4 끝에서 끝까지) → M3 다듬기와 평가(~11/26) ([product.md](product.md) 9절, 11/20 회의 [team/meetings/2026-11-20.md](team/meetings/2026-11-20.md))
- 기준 기획: [product/service_plan_v3.1.md](product/service_plan_v3.1.md). 3주 PRD: [product.md](product.md)
- 정함: 기술 구조 [ADR 0003](decisions/0003-tech-stack.md), 전체 설계 [architecture.md](architecture.md)·[data-model.md](data-model.md), API 명세 v0 [api/README.md](api/README.md). 다음: 코드 뼈대(이슈 #12)와 기능 문서 틀(이슈 #10·#11). 지원 거절이유는 진보성·명확성·신규성 (11/17 신규성 추가, [product.md](product.md) 3.2절). 대응 방향은 순위·이유·확신도까지 제시하기로 보완 ([ADR 0001](decisions/0001-ai-amended-claim-draft.md)). 지식 그래프는 M2에 벡터·BM25로 못 찾은 질문(CQ)을 모은 뒤 M3에 조건부로 넣기로 보완, 범위는 줄이지 않음 (11/18, [ADR 0002](decisions/0002-first-build-scope.md))

처음 온 사람(또는 새 Claude 세션)은 이 순서로 읽는다: 이 파일 → `product.md` → `architecture.md` → 맡은 기능의 `features/<기능>/requirements.md`.

## 무엇을 어디에 (새 문서를 만들기 전에 이 표를 본다)
| 폴더·파일 | 넣는 것 | 넣지 않는 것 |
|---|---|---|
| `product.md` | 3주 PRD (만들 기능·합격 기준·평가·마일스톤) + 기준 기획서 판(`기준:` 한 줄) | |
| `product/` | 기획에 쓰는 것 전부: 기획서 판(`service_plan_v<판>.md`)과 그 바탕이 되는 도메인 지식 `product/domain/` (주제마다 한 파일, 목차 `domain/README.md`, 출처·확인일·한계). 용어 표는 `product/domain/용어집.md`. 새 판은 새 파일로, 옛 판은 지우지 않는다 | 확정된 요약 (→ `product.md`), 법률 자문 |
| `architecture.md`, `api/` | 전체 설계, API 명세 | 기능 하나의 세부 (→ features) |
| `data-model.md` | 엔티티·관계, 공통 속성, 결과 스키마, DB 모델 | 기능 하나의 세부 (→ features) |
| `decisions/NNNN-<제목>.md` | ADR: 세 조건이 다 맞는 결정만 (되돌리기 어렵다 / 이유를 모르면 이상해 보인다 / 진짜 선택지가 있었다). 제안(비교 중) → 확정 → 대체됨 | 하나라도 아닌 선택 (→ 그 기능 design.md 결정 칸) |
| `features/<기능>/` | `requirements.md`(무엇) → `design.md`(어떻게) → `tasks.md`(구현 계획 + 진행) | 코드 (→ 코드 폴더) |
| `eval/GUIDE.md` | 정답 파일 형식·위치 (`data/goldsets/` 구조, 버전). `docs/` 밖 예외 (#9에서 정한 위치) | 정답 뽑는 규칙 (→ `evaluation/`) |
| `evaluation/` | 평가 세부: 지표 정의, 정답 뽑는 법, LLM 저지 루브릭과 예시·애매한 경우, 사람 검수 방법 (목차 `evaluation/README.md`, 단계마다 한 파일로 나눠도 된다) | 평가 원칙 (→ `product.md` 6절), 정답 원문 (→ `data/goldsets/`), 점수 (→ `experiments/`), 저지 프롬프트 원문 (→ `eval/` 프롬프트 파일) |
| `data/<출처>.md` | 데이터 카드: 출처·이용 조건, 필드, 품질 숫자, 가공 단계 (`data/_template.md`) | 원문, 개인정보 |
| `troubleshooting/YYYY-MM-DD-<제목>.md` | 팀원도 겪을 문제의 정제본 | 개인 상세 기록 (→ 각자 노트) |
| 루트 `CLAUDE.md`, 폴더별 `CLAUDE.md`, `.claude/rules/` | 팀 규칙과 그 예외, 폴더 규칙 | 규칙 후보 (→ `team/`). `docs/` 문서 안에는 규칙을 쓰지 않는다 |
| `team/` | 회고, 팀 규칙 후보, 질문, 회의록(`meetings/YYYY-MM-DD.md`: 정한 것 / 할 일 / 다음에 볼 것, 결정만 짧게) (`team/README.md`) | 개인 하루 로그, 개인 규칙 후보 |
| `assumptions.md` | 재 보지 않은 숫자 ([가정]) | |
| 저장소 어디에도 | | 원본 데이터, 비공개 샘플, 답 원문 로그 (→ `data/`, `work/`), `.env` |

- 실험 기록은 docs 밖 루트 `experiments/` (스크립트가 읽고 쓰는 설정·점수). 점수 표는 [experiments/index.md](../experiments/index.md).
- PR 본문은 문서의 집이 아니다. 문서는 여기에 두고 PR에서 링크한다.
- product.md·기획서·용어집 본문엔 지금 상태만 쓴다. 바뀐 내용은 PR·커밋에 남긴다 (ADR·조사 문서는 날짜를 남긴다).

## 기능
| 기능 | 담당 | 마일스톤 | 상태 | requirements | design | tasks |
|---|---|---|---|---|---|---|
| F1 OA 읽기·거절이유별 정리 | 재아 | M1 | 문서 초안, 구현 계획 승인 | [requirements](features/F1/requirements.md) | [design](features/F1/design.md) | [tasks](features/F1/tasks.md) · [tasks-2](features/F1/tasks-2.md) |
| F2 법률 근거 조사 | 은진 | M2 | 문서 승인, m2-i3 걷는 뼈대 구현, #24 law-idx-v3 | [requirements](features/F2/requirements.md) | [design](features/F2/design.md) | [tasks](features/F2/tasks.md) |
| F3 청구항–인용문헌 대비 | 재아 | M2 | 문서 초안 | [requirements](features/F3/requirements.md) | [design](features/F3/design.md) | |
| F4 대응 방향 후보와 초안 | 재아 | M3 | 문서 초안 | [requirements](features/F4/requirements.md) | [design](features/F4/design.md) | |
| F5 근거·상태 표시와 진행·보류 | 은진 | M1 | 문서 초안, 구현 계획 초안 | [requirements](features/F5/requirements.md) | [design](features/F5/design.md) | [tasks](features/F5/tasks.md) |
| F2·F3 공통 검색 계약 (이슈 #65) | 재아 | M2 | requirements·design 초안 | [requirements](features/retrieval/requirements.md) | [design](features/retrieval/design.md) | |
| F3 인용문헌 문단 검색 기준선 (이슈 #67) | 재아 | M2 | 하이브리드 RRF 기본으로 정함 (BM25·벡터·문헌 통째 LLM과 비교, 11/22 이슈 #248) | [requirements](features/cite-search/requirements.md) | [design](features/cite-search/design.md) | [tasks](features/cite-search/tasks.md) |

기능 번호·합격 기준은 [product.md](product.md) 5절. 기능 폴더(`features/<기능>/`)는 PRD 승인 뒤 만든다. 기술·경쟁사 조사, 선행기술 조사는 기획서에만 있다 (기획서 9절).

## 결정 (decisions/)
| 번호 | 제목 | 상태 | 날짜 |
|---|---|---|---|
| [0001](decisions/0001-ai-amended-claim-draft.md) | AI 대응 방향 제안·검토용 보정 청구항 초안 | 확정 (11/13 B안, 11/16 순위·이유·확신도 보완, 11/17 단위·기본 선택·확신도 3단계 보완) | 11/13 |
| [0002](decisions/0002-first-build-scope.md) | 3주 첫 구현 범위 | 확정 (11/16 보완, 11/18 보완: 그래프는 M3 조건부·범위 안 줄임, 11/22 보완: CQ 보고 그래프는 `cite`부터 M3 켬/끔, `law`에는 안 넣음) | 11/13 |
| [0003](decisions/0003-tech-stack.md) | 기술 구조 (앱·AI 코어·DB·에이전트·모델) | 확정 | 11/17 |
