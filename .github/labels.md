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
| 기능:<이름> | ededed | 그 기능의 이슈 (예: `기능:선행기술검색`). 기능이 정해질 때 하나씩 만든다. `/plan-feature`가 이슈에 붙인다 |

마일스톤(M1, M2 …)은 라벨이 아니라 **GitHub Milestone**으로, 이터레이션은 **Projects의 Iteration 칸**으로 둔다. 기능은 `기능:` 라벨로 묶는다 (하위 이슈는 쓰지 않는다). 보드에서 기능별로 보려면 Projects에서 라벨로 묶기.
