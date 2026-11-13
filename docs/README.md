# 문서 지도

## 지금
<!-- 프로젝트 전체 위치만 3줄. 기능 진행은 각 features/<기능>/tasks.md에. 결정이 나는 PR에서만 고친다. -->
- 단계: 기획 완료, M1~M3(3주) 준비. 기능 폴더 만들기 전 (11/13)
- 기준 기획: [product/service_plan_v3.1.md](product/service_plan_v3.1.md). 3주 PRD: [product.md](product.md)
- 다음 결정: [0003 프레임워크·기술 구조](decisions/0003-framework.md), 첫 지원 거절이유 (학습데이터 빈도 집계 뒤)

처음 온 사람(또는 새 Claude 세션)은 이 순서로 읽는다: 이 파일 → `product.md` → `architecture.md` → 맡은 기능의 `features/<기능>/requirements.md`.

## 무엇을 어디에 (새 문서를 만들기 전에 이 표를 본다)
| 폴더·파일 | 넣는 것 | 넣지 않는 것 |
|---|---|---|
| `product.md` | 기획안 요약 + 지금 기준 판이 무엇인지(`기준:` 한 줄) | |
| `product/` | 기획에 쓰는 것 전부: 기획 원본·판(`service_plan_v<판>.md`, `v<판>_변경안.md`), 기획 작업 문서(예: `s4-흐름.md`), 그 바탕이 되는 도메인 지식 `product/domain/` (주제마다 한 파일, 목차 `domain/README.md`, 출처·확인일·한계, 용어 표 `domain/용어집.md`). 새 판은 새 파일로, 옛 판은 지우지 않는다 | 확정된 요약 (→ `product.md`), 법률 자문 |
| `architecture.md`, `api/` | 전체 설계, API 명세 | 기능 하나의 세부 (→ features) |
| `decisions/NNNN-<제목>.md` | ADR: 세 조건이 다 맞는 결정만 (되돌리기 어렵다 / 이유를 모르면 이상해 보인다 / 진짜 선택지가 있었다). 제안(비교 중) → 확정 → 대체됨 | 하나라도 아닌 선택 (→ 그 기능 design.md 결정 칸) |
| `features/<기능>/` | `requirements.md`(무엇) → `design.md`(어떻게) → `tasks.md`(구현 계획 + 진행) | 코드 (→ 코드 폴더) |
| `data/<출처>.md` | 데이터 카드: 출처·이용 조건, 필드, 품질 숫자, 가공 단계 (`data/_template.md`) | 원문, 개인정보 |
| `troubleshooting/YYYY-MM-DD-<제목>.md` | 팀원도 겪을 문제의 정제본 | 개인 상세 기록 (→ 각자 노트) |
| `team/` | 데일리 스크럼, 회고, 팀 규칙 후보, 질문 (`team/README.md`) | 개인 하루 로그, 개인 규칙 후보 |
| `assumptions.md` | 재 보지 않은 숫자 ([가정]) | |
| 저장소 어디에도 | | 원본 데이터, 비공개 샘플, 답 원문 로그 (→ `data/`, `work/`), `.env` |

- 실험 기록은 docs 밖 루트 `experiments/` (스크립트가 읽고 쓰는 설정·점수). 점수 표는 [experiments/index.md](../experiments/index.md).
- PR 본문은 문서의 집이 아니다. 문서는 여기에 두고 PR에서 링크한다.

## 기능
| 기능 | 담당 | 마일스톤 | 상태 | requirements | design | tasks |
|---|---|---|---|---|---|---|
| F1 OA 읽기·거절이유별 정리 | | M1 | PRD | | | |
| F2 법률 근거 조사 엔진 | | M2 | PRD | | | |
| F3 청구항–인용문헌 대조 | | M2 | PRD | | | |
| F4 대응 방향 후보와 초안 | | M3 | PRD | | | |
| F5 근거·상태 표시와 진행·보류 | | M1 | PRD | | | |

기능 번호·합격 기준은 [product.md](product.md) 5절. 기능 폴더(`features/<기능>/`)는 PRD 승인 뒤 만든다. 기술·경쟁사 조사, 선행기술 조사는 전체 기획에만 있다 (기준 기획 9절).

## 결정 (decisions/)
| 번호 | 제목 | 상태 | 날짜 |
|---|---|---|---|
| [0001](decisions/0001-ai-amended-claim-draft.md) | AI 대응 방향 제안·검토용 보정 청구항 초안 | 확정 | 11/13 |
| [0002](decisions/0002-first-build-scope.md) | 3주 첫 구현 범위 | 확정 | 11/13 |
| [0003](decisions/0003-framework.md) | 프레임워크 | 제안 | |

## 기획에서 확정된 것 (ADR 없이)
| 무엇 | 고른 것 | 근거 |
|---|---|---|
| 서비스 구조 | Research(법률 조사, 기술·경쟁사 조사, 선행기술 조사) + 국내 OA 대응, 서로 독립, 고른 결과만 연동 | 기준 기획 3·4절 |
| AI·사람 책임 | AI는 찾기·대조·대응 방향 후보 2~3개·의견서 초안·검토용 보정 청구항 초안·검증. 사람은 방향 선택·보정 확정·법률 판단·승인 | 기준 기획 2절, [0001](decisions/0001-ai-amended-claim-draft.md) |
| Research 집중 대상 | 법률 조사. 기술·경쟁사, 선행기술은 구체화 안 함 | [0002](decisions/0002-first-build-scope.md) |
| 평가 깊이 | OA 대응·법률 조사 정량 (법률 조사는 근거 검토) | 기준 기획 12절 |
| 인용문헌 | 한국·미국 문헌만 | 기준 기획 6.1절 |
| 초기 기술 분야 | 컴퓨터 비전 (세부 미정) | - |
