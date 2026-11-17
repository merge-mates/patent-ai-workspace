# 라벨 (저장소 만든 날 한 번 만든다)
`gh label create <이름> --color <색> --description "<설명>"` 로 만든다. 기본 라벨 중 `bug`만 남기고 나머지는 지워도 된다.

| 라벨 | 색 | 뜻 |
|---|---|---|
| backend | 1d76db | 백엔드 |
| frontend | 0e8a16 | 프론트 |
| ai | 5319e7 | 모델·프롬프트·에이전트 |
| eval | fbca04 | 채점기·평가 세트 |
| docs | c5def5 | 문서 |
| infra | bfdadc | 설정·배포·CI |
| 실험 | f9d0c4 | 비교 실험 |
| 막힘 | b60205 | 다른 사람·외부 때문에 멈춤 |
| bug | d73a4a | 버그 |
| 기능:F1 ~ 기능:F5 | ededed | 그 기능의 이슈 (F1 OA 읽기·거절이유별 정리, F2 법률 근거 조사, F3 청구항–인용문헌 대비, F4 대응 방향 후보와 초안, F5 근거·상태 표시와 진행·보류). `/plan-feature`가 이슈에 붙인다 |

마일스톤은 라벨이 아니라 **GitHub Milestone**으로 둔다 (`M1 OA 정리` 11/19, `M2 근거와 대비` 11/24, `M3 대응 초안과 평가` 11/26). 이터레이션은 따로 칸을 두지 않고 `tasks.md`의 `## m1-i3` 이슈 계획 이름으로만 쓴다. 기능은 `기능:` 라벨로 묶는다 (하위 이슈는 쓰지 않는다).

진행 보드는 저장소 Projects 탭에 하나 (칸 Todo / In Progress / In Review / Done). 칸은 손으로 옮기지 않고 저절로 옮겨진다: [.claude/skills/README.md](../.claude/skills/README.md) `진행 보드` 절.
