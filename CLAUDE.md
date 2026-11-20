# 팀 규칙: Patent Professional AI Workspace

## 명령
- 앱 실행(DB·서버·화면): `make up`. 화면 http://localhost:5173, 서버 http://localhost:8000/health. DB만: `make db`. 목록 `make help`, 안내 [docs/team/local-db.md](docs/team/local-db.md).
- 테스트(파이썬): `uv run pytest` (`make test`). 네트워크·DB·API 키 없이 돈다. 실제 DB가 필요한 테스트는 `@pytest.mark.db`, `make db` 뒤 `make test-db`.
- 린트(파이썬): `uv run ruff check`, `uv run ruff format`. 설정은 `ruff.toml`.
- 화면(`web/` 안에서): `npm run lint`, `npm run build`(타입 검사 포함).
- 채점: `uv run python eval/run_eval.py --config experiments/<실험>/config.yaml` (설정 `feature:`로 채점기를 고른다: `retrieval`·`f1`. 그 밖의 명령은 짐작해서 돌리지 않는다). F1은 `--predictions <폴더>`(read_oa가 낸 OAResult JSON, git 밖)가 필요하고 `--pages <폴더>`(쪽 글자)는 고를 수 있다. 검색은 `--chunks`가 없으면 `DATABASE_URL`의 색인 DB를 읽는다. 점수 표: `uv run python eval/make_index.py`
- PR마다 GitHub Actions(`.github/workflows/ci.yml`)가 위 테스트·린트·빌드를 돈다.

## 폴더
- 사람이 읽는 문서는 전부 `docs/`. 무엇을 어디에 둘지는 [`docs/README.md`](docs/README.md) 표를 따른다. 새 문서를 만들기 전에 그 표를 본다.
- `experiments/<실험>/` 비교 실험 하나: `card.md`, `config.yaml`, `scores.json`. `experiments/index.md`는 스크립트가 만든다. 손으로 고치지 않는다.
- `eval/` 채점기. 평가 세트(정답)는 git 밖 `data/goldsets/`에 둔다. 앱 코드는 `data/goldsets/`를 불러오지 않는다 (채점기만 읽는다. 예외: `scripts/split_cases_at_oa.py`가 AI 입력을 만들려고 `tune/case_full/`을 읽는다).
- `data/raw/`(받은 원본, Claude는 직접 안 고침) → 스크립트 → `data/processed/`. `data/goldsets/report/`는 Claude가 읽지 않는다 (채점기만 읽는다). 데이터를 다루기 전에 `docs/data/<출처>.md` 데이터 카드를 본다.
- `data/`, `work/`는 git 제외. 원본 데이터·비공개 샘플·API 키는 어떤 커밋에도 넣지 않는다.
- DB는 각자 로컬 Postgres + pgvector(docker compose)다. 스키마는 Alembic 마이그레이션으로만 바꾸고, DB를 SQL로 손으로 고치지 않는다. 자세한 건 `src/patent_ai/db/CLAUDE.md`.
- 공유 자원(DB 마이그레이션, 검색 색인 스크립트·설정, 평가 세트, 데이터 카드, 결과 스키마 `core/schemas/`)은 PR로만 바꾸고 상대가 리뷰한다.
- 부르는 방향은 `api → core → retrieval·law_api·db`, 그리고 `retrieval → db`만이다 ([ADR 0003](docs/decisions/0003-tech-stack.md)). `db/`에는 표 정의(ORM 모델)만 두고 core·retrieval을 import하지 않는다. core 타입을 DB에 쓰고 읽는 저장소(repository)는 부르는 쪽(core 또는 retrieval)에 둔다.

## 진행 단위
- 지금 위치와 문서 지도: @docs/README.md (맨 위 `지금`)
- 진행은 각 기능의 `tasks.md`에만 쓴다 (기능마다 주인 한 명이라 둘이 같은 줄을 안 고친다). 작은 이슈(`일하는 순서` 1번)는 이슈 본문 체크리스트에 쓴다. `docs/README.md`의 `지금`·결정 표는 프로젝트 전체 위치만 두고, 결정이 나는 PR에서만 고친다. 충돌이 나면 나중에 머지하는 쪽이 맞춘다.
- 단위: 기능 = 사용자가 말로 설명할 수 있는 결과 하나(합격 기준 3~7개). 이슈 = 그 기능을 이번 이터레이션에 어디까지(task 2~5개, `tasks.md`의 `## m1-i3` 이슈 계획 하나. 작은 이슈는 이슈 본문). task = 혼자 끝나고 혼자 검증되는 가장 작은 단위(atomic). 반나절 안쪽, 목적 하나. 커밋 몇 개(각 커밋은 테스트 통과), 확인 방법(명령 한 줄)이 있다. **계획 하나 = 브랜치 하나 = PR 하나** (400줄은 나눌지 보는 기준. 넘으면 PR 본문에 커밋별 리뷰 순서를 적는다. 병렬로 갈 수 있으면 나눈다). 이슈 하나에 PR 여러 개를 붙일 수 있다 (먼저 머지되는 PR은 `Refs #N`, 마지막 PR이 `Closes #N`). 이슈는 사람이 진행을 보는 단위로 둔다. 마일스톤 ⊃ 기능(의 일부) ⊃ 이슈 ⊃ task. 기능은 `기능:<이름>` 라벨로 묶는다.
- 작은 기능(하루 안 + 인터페이스 안 바뀜 + 비교 실험 아님)은 `design.md` 없이 requirements + tasks만.
- 마일스톤(product.md 9절: M1 OA 정리, M2 근거와 대비, M3 대응 초안과 평가) > 이터레이션(하루~이틀, `M1-i3`). 구현 계획은 `tasks.md`의 `## m1-i3` 이슈 계획, 실험은 `experiments/m1-i3-<기능>-<바꾼 것>/`.
- 기능마다 requirements.md의 `비교 실험` 칸으로 정한다. **아니오** = 한 사람에게 배정. **예**(AI 품질이 핵심) = 둘이 각자 구현할지, 한 사람이 구현하고 같은 인터페이스 뒤에서 설정(`impl`, 모델, 하이퍼파라미터)만 바꿔 비교할지는 그 이터레이션을 시작할 때 정한다. 어느 쪽이든 같은 평가 세트로 채점해 하나를 채택한다. 같이 정하는 것은 design.md의 공통 칸(인터페이스, 평가 세트·지표, 데이터, 채점 스크립트)이다. 고른 방식은 그 기능 design.md의 결정 칸에 적는다.

## 일하는 순서
1. 무엇을 할지는 `docs/features/<기능>/requirements.md`, 어떻게는 `design.md`, 이번 이터레이션 할 일은 `tasks.md`. task를 끝내면 그 계획의 진행 칸을 고친다. 구현 계획이 없으면 구현하지 않는다 (아주 작은 일 제외: 문구, 설정 한 줄). 기능 문서 없이 끝나는 작은 이슈(반나절~하루, 인터페이스 안 바뀜)는 이슈 본문의 task 체크리스트와 확인 명령 한 줄을 구현 계획으로 본다. 기능 밖 이슈(설정·스크립트 등)도, 기능 안 이슈도 된다 (위 `작은 기능`은 기능 하나 전체가 작을 때라 다르다). 기능 안 이슈면 그 기능 `tasks.md`가 생긴 뒤 거기에 이슈 링크만 남긴다.
2. 테스트 먼저: 합격 기준에서 테스트를 쓰고, 실패를 확인하고(로컬에서만), 구현한다. 커밋은 통과한 뒤 테스트와 구현을 함께 한다 (`.claude/rules/git.md`). 기대값은 구현 계획·예시에서 가져오고 구현을 보고 정하지 않는다. (예외: 프롬프트 문구, 실험 스크립트)
   - 테스트 범위: 정해진 일을 하는 코드 도구와 꼭 지킬 선(사람 승인·누락 검사 등)은 테스트를 촘촘히 둔다. AI 품질은 테스트가 아니라 tune 세트 점수로 본다. 앱은 주요 API 테스트와 끝에서 끝까지(E2E) 하나. 프롬프트 문구·화면 스냅샷은 테스트하지 않는다.
3. 커밋 전에 그 폴더 전체 테스트를 통과시킨다.
4. "끝났다" = 합격 기준 테스트 통과 + 돌려 볼 명령 한 줄 + (AI 동작을 바꾼 이슈면) tune 세트 점수 한 줄 + 상대 PR 승인. 마일스톤 끝에는 report 세트로 한 번.

## 특허 도메인 규칙
- 기획 기준은 `docs/product.md` 맨 위 `기준:`에 적힌 판 하나다. 다른 문서(작업 문서, 개인 노트)는 그 판을 대체하지 않는다. 합의와 제안이 다르면 `docs/decisions/`의 상태를 본다. 제안을 확정 기능처럼 구현하지 않는다.
- AI는 법률 결론·대응 방향 확정·보정 적법성 판정·등록 가능성 보증·자동 제출을 하지 않는다. 대응 방향은 순위·이유·확신도까지 제시하고(확신이 낮으면 "직접 판단 필요"), 고르고 제출하는 것은 사람이다. 사람의 판단과 AI 결과를 화면과 데이터에서 구분한다.
- OA 당시 청구항, 최초 명세서, 공개·등록공보 청구항은 다른 판이다. 출원번호 + 발송번호(OA) / 접수번호(보정)로 묶고, 날짜만으로 합치지 않는다.
- 검색에서 못 찾음 ≠ 없음. 결과 상태는 최소 `확인됨 / 조회 범위 내 없음 / 확인되지 않음 / 충돌` 으로 나눈다.
- 법령·심사기준은 출처와 적용 시점·판본을 같이 저장한다. 판본을 모르면 "확인되지 않음"을 돌려준다.
- 데이터의 존재 안내, 파일 확보, 원문 열람, 사건 연결, 이용 권한, 성능은 다른 단계다. 외부 모델로 보내도 되는 자료와 git·공개 배포에 넣지 않는 자료는 [전체 설계](docs/architecture.md)의 "외부 모델로 보내는 자료" 표를 따른다.
- 신뢰할 수 없는 pickle은 역직렬화하지 않는다.
- 사건 진행을 에이전트가 정하는 범위, 에이전트가 골라 부르는 코드 도구, 무조건 도는 코드 단계의 경계는 [ADR 0003](docs/decisions/0003-tech-stack.md)을 따른다.

## Git
- 흐름은 GitHub flow: main에서 브랜치 → PR → merge commit으로 머지 → 브랜치 삭제 (쌓인 PR을 머지해도 위 브랜치를 옮기지 않도록 squash는 쓰지 않는다). 브랜치는 이터레이션 하나(하루~이틀) 안에 끝낸다. develop·release 브랜치는 없다. 마일스톤 끝에 태그(`m1`).
- `main`에 직접 푸시하지 않는다. Claude는 `git add -f`로 gitignore된 파일을 넣지 않는다 (settings로 막힘). 브랜치: `<type>/<이슈번호>-<짧은설명>` (예: `feat/12-<기능>-baseline`). 둘이 같은 기능을 각자 구현할 때만 뒤에 사람: `feat/12-<기능>-<사람>`.
- 커밋 제목: `<type>(<영역>): <한국어 한 줄>`. type은 `feat` `fix` `test` `refactor` `docs` `chore`, 영역은 `backend` `frontend` `ai` `eval` `docs` `infra`. 자세한 건 `.claude/rules/git.md`.
- PR 하나 = 계획 하나 (이슈 하나에 PR 여러 개 가능). 제목은 커밋 제목 모양 (merge commit 제목이 된다). 본문은 `.github/pull_request_template.md` 칸을 채우고, 그 이슈의 마지막 PR이면 `Closes #N`, 아니면 `Refs #N`.
- 이슈 일은 `/start <이슈번호>`로 시작한다. 진행 보드(Projects 탭) 카드는 스킬이 옮긴다: `/start`는 In Progress, `/pr-draft`는 `Closes` PR을 만든 뒤 In Review(`Refs` PR은 그대로), 마지막 PR이 머지되면 Done(보드 규칙). 훅은 쓰지 않는다. 보드 번호·id는 적지 않는다 (`.claude/scripts/board-status.sh`가 찾음).
- 남의 브랜치를 merge·rebase하지 않는다. 커밋은 Claude가 해도 된다. push와 PR 생성은 매번 사람이 승인한다 (확인 창). 사람이 `/pr-draft` 초안을 보고 OK하면 Claude가 한다. `main`에 직접 push하지 않는다. 머지는 사람이 한다.

## 코드 규칙 (공통)
- 스타일은 린터(위 명령)가 본다. 리뷰에서 스타일을 지적하지 않는다.
- 모델 호출은 한 곳(모델 호출 모듈)에서만 한다. 외부 API 호출은 캐시와 호출 상한을 거친다.
  - 예외: 한 번 쓰는 데이터 받기 스크립트(`scripts/fetch_*.py` 같은 수집용. `scripts/db/` 같은 앱 설정 스크립트는 아님)와 사람이 돌려 기록된 모델 응답을 만드는 `scripts/record_llm.py`는 캐시·호출 상한을 안 거친다. 대신 이미 있는 파일이면 멈추고, 호출 사이를 두고, 키를 출력·저장하지 않는다. 앱 코드는 위 규칙대로.
- 테스트는 네트워크·API 키 없이 돈다. 외부 API 응답은 저장해 둔 파일(기록된 모델 응답, recorded response)로 테스트한다.
- 프롬프트는 코드와 분리한 파일로 둔다. 실험할 값(모델, 하이퍼파라미터)은 실험 설정(config) 파일에서 읽는다. 각자 구현은 같은 인터페이스 뒤에 두고 config의 `impl`로 고른다 (전략 패턴).
- 목록이 0개처럼 비면 경고를 남긴다. 실패했는데 성공 종료하거나 이유 없이 끝나지 않는다.
- `.env`에는 비밀 키와 컴퓨터마다 다른 값(포트·`DATABASE_URL`)만. 모델·실험 값은 설정 파일(`config/`)에. `.env`는 읽지도 출력하지도 않는다.

## 리뷰 심각도 (사람·에이전트 공통)
- 막음: 합격 기준 못 지킴, 테스트 실패, 위 규칙 위반, 평소 입력에서 결과가 틀림, 조용한 실패, 비공개 내용·키가 새는 경로.
- 고칠 것: 결과는 맞지만 다음 이터레이션에 짐 (약한 테스트, 이름 어긋남, 중복).
- 참고: 구현 계획 밖, 드문 경우, 취향. 결과물 모양·비용·보안·설계와 다르게 가자는 것은 앞에 `[사람 판단]`.
- 재리뷰는 막음이 있었을 때만, 바뀐 부분만, 최대 2회.

## 하위 규칙
- 코드 폴더별 `CLAUDE.md`는 폴더를 만들 때(프레임워크를 정한 뒤) 둔다. 앱 폴더(`src/patent_ai/api/`, `web/`)는 그 폴더 `CLAUDE.md` 규칙을 따른다 (테스트 먼저 대신 API 테스트 몇 개). AI 코어(`src/patent_ai/core/`)는 위 "일하는 순서" 그대로. `eval/`·`experiments/` 규칙은 `.claude/rules/eval.md`(그 경로를 다룰 때만).
- 이 파일은 200줄 아래로 둔다 (공식 문서 권장). 한 기능에만 맞는 내용은 여기 말고 `docs/features/<기능>/design.md`에.
- 절차는 스킬로 부른다. 목록·순서·쓰임은 [`.claude/skills/README.md`](.claude/skills/README.md).
- 개인 규칙은 각자 `CLAUDE.local.md`(git 제외). 팀 규칙과 부딪히면 이 파일이 이긴다.
