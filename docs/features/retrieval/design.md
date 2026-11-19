---
상태: 초안   # 초안 → 승인
기능: F2·F3 공통 (검색 계약)
마일스톤: M2
담당: 재아
requirements: ./requirements.md
---
# 검색 계약 세부 설계
<!-- 이슈 #65. requirements에 쓴 것(무엇, 합격 기준, 사람이 고르는 곳)은 다시 쓰지 않고 번호로 가리킨다.
     "판"은 셋으로 나눠 쓴다: 법령 판본(시행일별 법령·심사기준) / 공보(인용문헌 공개·등록) / 색인 판(index_version). -->

## 1. 합격 기준 ↔ 설계
| 기준 (requirements 번호) | 설계의 어디가 만족시키나 |
|---|---|
| 1 검색 | 7-1 `Searcher` 인터페이스·`SearchResult`, 7-2 `fake` 구현, 2절 흐름 1~4 |
| 2 조각 표와 덤프 | 5절 `law_chunks`·`cite_chunks`, 5-2 덤프 |
| 3 채점 계산 (공통) | 7-1 채점기 `score()`, 7-3 계산식, 2절 흐름 5~8 |
| 4 맞음 판정 (말뭉치마다) | 7-1 `Matcher` 인터페이스, 7-4 판정 규칙 |
| 5 CQ 후보 | 7-1 CQ 파일, 7-5 CQ 모으기 |
| 6 덤프 마이그레이션 검사 (있으면 좋음) | 5-2 revision 옆 파일 |
| 7 실제 DB (있으면 좋음) | 9절 `@pytest.mark.db` 테스트, 5-1 Postgres 저장소 |

## 2. 흐름
```mermaid
flowchart LR
    C[실험 설정 config.yaml] --> V{색인 판·정답 파일·질의 누출 검사}
    V -- 하나라도 걸림 --> X[점수 없이 실패로 끝남]
    V -- 통과 --> S[정답 줄마다 search]
    S --> M[Matcher로 맞음 판정]
    M --> K[Hit@k·Recall@k·무작위 기준선]
    K --> O1[scores.json: 숫자·건수만]
    M --> O2[CQ 후보 파일: git 밖]
    O2 -- 0건 --> W[경고]
```
1. 입력: 실험 설정(`experiments/<실험>/config.yaml`), 정답 파일(`data/goldsets/tune/retrieval/gold.jsonl`), 조각 저장소. 저장소는 CLI `--chunks <jsonl>`을 주면 메모리 저장소이고, 없으면 Postgres다 (7-1 채점기).
2. 실행 전 검사 (requirements 기준 3):
   - `index_version`이 그 말뭉치 표에 있는지
   - 정답 파일이 있고 1줄 이상인지
   - 질의에 그 줄 정답 위치 표기가 있는지 (7-3 누출 검사)
   - 설정의 `goldset_version`이 `<goldsets_root>/VERSION`과 같은지. 정답 파일은 `<goldsets_root>/<goldset>/<gold>`로 읽고, `gold:`에 `..`이나 절대 경로가 있으면 멈춘다 (세트 폴더 밖을 못 가리키게).
   - CQ 출력 폴더(`--cq-dir`)가 git에 들어갈 수 있는 경로면 멈춘다. CQ 후보에 정답 위치·질의가 들어가기 때문이다. 판정: 저장소 밖이면 통과, 저장소 안이면 `git check-ignore`로 무시되는 경로여야 통과 (기본 `work/retrieval/<실험>/`은 통과).
   - `--chunks`(메모리 저장소)로 돌리는데 출력 폴더가 `experiments/` 아래면 멈춘다. 가짜 조각 점수가 실험 표에 섞이지 않게 하려는 것이다 (7-1 채점기).
   - 하나라도 걸리면 `RetrievalEvalError`로 끝나고 종료 코드는 1이다.
3. 검색 전에 뺄 줄: `exclude` 칸이 있는 줄, 법령 정답 판본이 `unverified`인 줄. 뺀 줄은 이유별로 센다. 정답 변환(`law_gold.py`)은 사람이 고른 판의 시행 시작일이 발송일 뒤면 그 항목을 `unverified`로 두고 경고한다 (#129). 그래서 이 경우는 `excluded_edition_unverified`로 빠지고 경고에 이유가 남는다.
4. 줄마다 `search(query, corpus, mode, k=max(k 목록), doc_ids, as_of)`를 한 번 부른다. 작은 k는 같은 결과의 앞부분을 잘라 쓴다.
   - 본문 미확보는 여기서만 정한다: 결과 `status`가 `unverified`(`body_missing`)면 그 줄을 빼고 `excluded_body_missing`에 센다.
   - 기준일 범위 내 판본 없음: 문헌 조각은 있는데 `as_of`로 거르고 나면 검색 범위 조각이 0개인 줄(N = 0)은 무작위 기준선을 정할 수 없으므로 채점 전체를 멈추지 않고 그 줄만 빼고 `excluded_no_edition_in_scope`에 센다 (11/19 결정). 법령 판본 모름 조각만 있거나, OA 발송일이 색인의 가장 이른 법령 판본보다 앞서는 경우다.
   - 범위 안에 정답 조각 없음 (#129): 범위 조각은 있는데 맞는 조각이 0개(Mᵢ = 0)인 정답 항목은 검색기가 어떻게 해도 못 맞힌다. 법령은 정답 판이 그날 범위에 없는 경우(받은 판 사이 빠진 개정, 판 하나가 통째로 없음), 인용문헌은 공보 조각은 있는데 정답 문단·도면이 어느 조각에도 없는 경우(청킹·정답 문제)다. 데이터 문제가 "검색이 못 찾은 질문"처럼 Hit·Recall을 내리고 CQ 후보에 섞이지 않게 한다.
     - 항목이 모두 Mᵢ = 0이면 줄째 빼고 `excluded_gold_not_in_scope`에 센다.
     - 일부만 Mᵢ = 0이면 그 항목만 빼고 남은 항목으로 Hit·Recall·CQ를 매기며, 뺀 항목 수를 `excluded_gold_items_not_in_scope`에 센다. 다른 항목으로 맞힌 줄까지 빼면 점수가 오히려 내려간다 (11/19 인용문헌 기준선: 그렇게 빠지는 9줄 중 8줄이 다른 항목으로 맞힌 줄).
     - 세 제외의 경계: 공보·법령 조각이 아예 없으면 `excluded_body_missing`, 조각은 있는데 기준일로 거르니 0개면 `excluded_no_edition_in_scope`, 범위는 있는데 정답 조각이 없으면 위 두 키. 이 순서로 먼저 걸린 하나에만 센다.
   - 결과에 다른 색인 판 조각이 있으면 실패로 끝난다. 판정은 조각마다 `hit.index_version`이 설정의 `index_version`과 같은지로 한다 (공통 래퍼가 먼저 보고, 채점기가 한 번 더 봄).
5. 3·4번에서 빼고 남은 줄이 0개면 실패로 끝난다 (종료 코드 1, `RetrievalEvalError`). 빈 평균으로 성공 종료하지 않는다.
6. 결과 조각마다 그 말뭉치 `Matcher`로 정답 항목과 맞는지 본다.
7. k마다 줄 Hit·Recall, 무작위 기대값을 계산한다 (7-3).
8. 결과 저장: `<scores 폴더>/scores.json`(모은 숫자, 기본 `experiments/<실험>/`), `<cq 폴더>/cq_candidates.jsonl`(CQ 후보, 기본 `work/retrieval/<실험>/`).
- 실패하면: 실행 전 검사가 막는다. 줄 하나의 검색이 예외를 내면 그 줄에서 멈추고 실패로 끝난다 (조용히 건너뛰지 않음).
- 메시지 규칙 (requirements "실패할 때"): 터미널 실패·경고 메시지에는 `row_id`와 건수를 쓸 수 있다. 질의·청구항·정답 원문 글자는 쓰지 않는다. git에 들어가는 `scores.json`에는 `row_id`도 쓰지 않는다.
- 비면: 검색 범위 조각은 있는데 검색 결과가 0개면 `not_found_in_scope`이고, 그 줄은 Hit 0이며 CQ 후보가 된다 (정답 조각이 범위에 있을 때만. 없으면 위 4번 범위 밖 정답 규칙). 범위 조각 자체가 0개면 위 4번처럼 뺀다. 거른 문헌 조각이 0개면 `unverified(body_missing)`이고 점수에서 뺀다. CQ 후보 0건이면 경고한다.
- 느리면: 가짜 구현만 있는 이 이슈에는 해당 없음. 진짜 구현의 상한은 #66·#67 설정에 둔다.

### 2-1. 흐름 방식
- 코드 흐름. 에이전트 루프가 아니다. 채점기는 정해진 순서로 돌고, `search`는 에이전트가 고르는 코드 도구다 ([ADR 0003](../../decisions/0003-tech-stack.md)).
- 루프 아님: 해당 없음.
- 단계 기록: 채점기는 `runs`·`agent_steps`에 쓰지 않는다. 결과는 `scores.json`과 CQ 파일뿐이다.

## 3. 데이터 모양
### 3-1. 앞 기능에서 받는 것
- 해당 없음. 앞 기능 결과 스키마를 받지 않는다. 정답 파일은 변환 스크립트(#66·#67)가 만든다.
- 받은 결과가 "확인되지 않음"·"충돌"이면: 해당 없음. 정답 줄의 본문 미확보·판본 모름은 2절 3번처럼 뺀다.

### 3-2. 다음 기능에 주는 것
검색 결과 `SearchResult` (F2 심사기준·판례 검색, F3 문헌 문단 검색 도구가 그대로 돌려준다):
```json
{
  "corpus": "cite",
  "index_version": "cite-idx-v1",
  "mode": "bm25",
  "scope": {"doc_ids": ["KR20190012345A"], "as_of": null, "k": 5},
  "status": null,
  "status_reason": null,
  "skipped_unverified_edition": 0,
  "hits": [
    {
      "chunk_id": "cite-idx-v1:KR20190012345A:p0023",
      "index_version": "cite-idx-v1",
      "doc_id": "KR20190012345A",
      "chunk_kind": "body",
      "location": {"kind": "paragraph", "start": 23, "end": 23, "label": "[0023]", "figures": [], "claims": []},
      "edition": {"status": "not_applicable", "effective_from": null, "effective_to": null, "label": null},
      "text": "…",
      "score": 3.2,
      "rank": 1
    }
  ]
}
```
- `SearchHit` = 조각 `Chunk`의 칸(5-1 표에서 `embedding`·`created_at` 뺀 것) + `score` + `rank`다. `Chunk`도 `retrieval/schemas.py`에 둔다. 저장소는 `Chunk`를 돌려주고 `Matcher`는 `Chunk`를 받으므로(7-1), 검색 결과와 무작위 기준선 계산이 같은 판정을 쓴다.
- `status`는 결과가 비었을 때만 값이 있다: `not_found_in_scope`(찾아본 범위는 `scope`) 또는 `unverified`(`status_reason: "body_missing"`, 거른 문헌 조각이 0개). 이름은 결과 공통 칸 `core/schemas/common.py`(#103)의 `body_missing`과 같다.
- 결과가 있으면 `status`는 `null`이다. 조각은 근거 **후보**이고, "확인됨"은 뒤의 출처 확인 단계가 붙인다 ([architecture.md](../../architecture.md) 8절). 공통 속성은 [data-model.md](../../data-model.md) 3절 그대로 쓰고, 여기서 새로 정하는 값은 `edition.status: not_applicable`(인용문헌) 하나다 (`status_reason: body_missing`은 #103 공통 칸 이름을 그대로 씀).
- 다시 확인 필요: 해당 없음 (검색은 저장하지 않는 도구 결과).
- 인터페이스 변경: 있음 (새로 생김). F2·F3 설계가 이 모양을 받는다. 스키마는 `src/patent_ai/retrieval/schemas.py`에 둔다. `core/schemas/`에 두지 않는 이유는 부르는 방향이 `core → retrieval`이라 `retrieval`이 `core`를 import하면 안 되기 때문이다 ([ADR 0003](../../decisions/0003-tech-stack.md) 폴더). data-model 4절 표에 "도구 결과" 줄로 이름을 더하는 것은 스키마 코드를 만드는 구현 task에서 한다.

## 4. 판과 근거
- 쓰는 청구항 판: 인용문헌 정답 줄의 질의 = OA 당시 청구항 전문. 어느 판인지는 정답 파일을 만드는 변환 스크립트가 출원번호 + 발송번호로 고른다 (#67). 이 계약은 질의 글자만 받는다.
- 쓰는 법령 판본: 정답 줄의 `as_of`(OA 발송일)로 `search`가 그날 시행 중인 법령 판본 조각만 거른다. 조각의 `edition.effective_from ≤ as_of ≤ effective_to`(끝이 없으면 현행). 법령 판본 상태가 `unverified`인 조각은 기준일 검색에서 빠지고 `skipped_unverified_edition`에 센다.
- 공보: 인용문헌 조각의 `doc_id`는 공보 번호(나라 + 번호 + 종류 코드, 예 `KR20190012345A`, `US10123456B2`)다. 공보 번호는 [docs/evaluation/f1-oa-gold.md](../../evaluation/f1-oa-gold.md) 2.3 키 꼴을 따른다. 번호 정규화 규칙은 #67이 정하고, 이 계약은 같은 문자열끼리만 같다고 본다.
- 근거 위치 적는 법: `doc_id` + `location`(종류·시작·끝·원문 표기 `label`) + `edition` + `index_version`. 화면 연결은 F2·F3 설계.

## 5. 저장
- 읽는 테이블: `law_chunks`, `cite_chunks` (검색·채점). 쓰는 테이블: 같은 둘 (색인 스크립트, #66·#67). 실행 결과 표(`runs` 등)는 쓰지 않는다.
- 검색: BM25와 벡터 둘 다. BM25는 Postgres 밖(Python)이고 ([ADR 0003](../../decisions/0003-tech-stack.md) 127줄), 진짜 구현은 #66·#67이다. 벡터는 `embedding` 칸이다.
- 외부 API에서 받는 자료: 이 이슈에는 없다.
- 외부 모델로 보내는 자료: 이 이슈에는 없다 (임베딩 호출은 #66·#67, [architecture.md](../../architecture.md) 7절 "법령·인용문헌 원문 보냄").

### 5-1. 조각 표 (마이그레이션 하나로 두 표)
두 표의 칸은 같다. ORM은 공통 mixin `ChunkColumns` 하나에 `LawChunk(__tablename__="law_chunks")`, `CiteChunk(__tablename__="cite_chunks")`다.

| 칸 | 타입 | 뜻 |
|---|---|---|
| `chunk_id` | text PK | 내용으로 정함 `<index_version>:<doc_id>:<위치 키>`. 같은 설정으로 다시 만들면 같은 ID (#66·#67 "두 번 만들면 같다") |
| `index_version` | text not null | `<말뭉치>-idx-v<n>`. 정규식 `^(law|cite)-idx-v[0-9]+$`, 말뭉치와 표가 맞아야 함 (CHECK) |
| `doc_id` | text not null | 법령: 법령 이름·심사기준·판례 사건번호 등 (#66이 값 규칙), 인용문헌: 공보 번호 |
| `chunk_kind` | text not null | `body` 본문 문단 / `claim` 청구항 / `abstract` 요약 / `figure_desc` 도면의 간단한 설명 / `article` 조문 / `guideline` 심사기준 문단 / `judgment` 판결 이유. 값을 더하면 이 문서를 고치는 PR |
| `loc_kind` | text not null | `paragraph` / `column_line` / `article` / `page` / `figure` / `claim` / `abstract` |
| `loc_start`, `loc_end` | integer null | 정렬 키. 문단 = 번호, 칼럼:줄 = 칼럼 × 10000 + 줄, 쪽 = 쪽 번호, 조문 = #66이 정함 (그 전엔 null) |
| `loc_figures`, `loc_claims` | integer[] not null default `{}` | 그 조각이 담은 도면 번호·청구항 번호 |
| `loc_label` | text not null | 원문 표기 그대로 (`[0023]`, `3:10-25`, `제29조 제2항`, `4206쪽`) |
| `edition_status` | text not null | `confirmed` / `unverified` / `not_applicable`(인용문헌). 법령 판본을 모르면 `unverified`, 빈칸 안 됨 |
| `edition_effective_from`, `edition_effective_to` | date null | 법령 판본 시행 기간 |
| `edition_label` | text null | 예 `특허청 예규 제113호` |
| `text` | text not null | 본문 |
| `embedding` | `vector` (길이 안 정함) null | 색인 판마다 모델이 달라도 담음. 인덱스 없음 ([가정] 5번) |
| `created_at` | timestamptz not null | |

- 인덱스: `(index_version, doc_id)`, 법령 표는 `(index_version, edition_effective_from)`.
- 마이그레이션은 `CREATE EXTENSION IF NOT EXISTS vector`를 먼저 한다. 그래서 DB 첫 생성 때 확장을 만들던 `scripts/db/init.sql`은 지운다 (#79 때 정한 대로).
- 폴더: ORM 모델은 `src/patent_ai/db/models/chunks.py`, 인터페이스 `ChunkRepository`·`InMemoryChunkRepository`·`PostgresChunkRepository`는 `src/patent_ai/retrieval/repository.py`. 부르는 방향에 `retrieval → db`를 더한다. db는 retrieval을 import하지 않는다. ([ADR 0003](../../decisions/0003-tech-stack.md) 폴더 절에 같은 문장)
- 저장소 인터페이스 `ChunkRepository`(조각 읽기·셈)를 두고, 테스트는 `InMemoryChunkRepository`(fixture JSONL을 읽음), 실제는 `PostgresChunkRepository`(기준 7, 있으면 좋음)다. 둘 다 같은 거르기(색인 판·문헌·기준일)를 한다.

### 5-2. 덤프 ([db/CLAUDE.md](../../../src/patent_ai/db/CLAUDE.md) 검색 색인 절)
- `make index-dump CORPUS=law` → `pg_dump -Fc -t law_chunks` → `data/index/law-idx-<그 표의 가장 높은 색인 판>.dump`. 그 표의 모든 색인 판이 들어간다.
- 같은 이름 옆에 `law-idx-v1.revision`(만든 DB의 Alembic revision 한 줄)을 쓴다.
- 같은 이름 옆에 `law-idx-v1.fingerprint.json`(색인 지문)도 쓴다. 색인 판마다 `{"chunks": 조각 수, "chunk_ids_sha256": chunk_id를 정렬해 줄바꿈(`\n`)으로 이은 UTF-8 글자의 sha256}`이고, 파일 모양은 `{"corpus": "law", "versions": {"law-idx-v1": {...}}}`다. 색인 판 이름만 같고 내용이 다른 경우(같은 이름으로 다시 만듦, 덜 받음)를 잡는다 (11/19 리뷰). 채점기 `scores.json`의 색인 지문도 같은 계산이다 (7-3).
- `make index-load DUMP=…`는 넣기 전에 옆 `.revision`·`.fingerprint.json`이 둘 다 있는지 보고(하나라도 없으면 덜 받은 것이라 멈춤), revision이 `alembic current`와 다르면 멈춘다 (기준 6, 있으면 좋음). 넣은 뒤 DB를 다시 세어 지문이 옆 파일과 다르면 종료 1이다.
- 명령 구현은 tasks.md에서 한다.

## 6. 화면 (시연용)
- 해당 없음 (화면 없음).

## 7. AI
### 7-1. 공통 칸 (#66·#67이 그대로 쓰는 계약)
**검색 인터페이스** (`src/patent_ai/retrieval/`)
```python
class Searcher(Protocol):
    def search(self, query: str, corpus: Corpus, mode: Mode, k: int,
               doc_ids: list[str] | None = None, as_of: date | None = None) -> SearchResult: ...

def get_searcher(impl: str, repo: ChunkRepository, settings: dict, embed: Callable[[str], list[float]] | None = None) -> Searcher  # 없는 이름 → UnknownImplError(이름 규칙 + 쓸 수 있는 이름 목록)
```
- `get_searcher`는 등록된 구현을 공통 검사 래퍼 `CheckedSearcher`로 감싸 돌려준다. 어느 구현이든 아래 검사를 래퍼가 하므로 #66·#67은 구현에서 다시 하지 않아도 된다.
  - 부르기 전: `k ≥ 1`(아니면 `ValueError`), `corpus`·`mode` 값(아니면 `ValueError`), `mode == "hybrid"`면 `ModeNotSupportedError`, `settings["index_version"]`이 그 말뭉치에 없으면 `UnknownIndexVersionError`.
  - 받은 뒤: `result.corpus`·`result.mode`·`result.scope.k`가 요청과 같음(아니면 `SearchContractViolationError`), 결과 조각 수 ≤ k, 모든 `hit.index_version == settings["index_version"]`(아니면 `IndexVersionMismatchError`), 점수 내림차순·같은 점수는 `chunk_id` 오름차순.
- 색인 판은 `settings["index_version"]`으로 넘긴다 (`search()` 인자에는 없음). `SearchResult.index_version`도 이 값이다.
- `Corpus = Literal["law", "cite"]`, `Mode = Literal["bm25", "vector", "hybrid"]`.
- `impl`은 이름 → 클래스 등록표(`register_impl("fake")`)로 고른다. #66·#67은 새 이름만 등록하고 이 파일들은 고치지 않는다.
- `get_searcher`는 설정 `impl` 이름으로 구현 모듈 `patent_ai.retrieval.<impl>`을 그때 import한다 (등록표에 이미 있으면 import하지 않음). 그래서 구현 파일 이름 = `impl` 이름이고(예 `impl: fake` → `retrieval/fake.py`), 그 모듈이 `@register_impl("<impl>")`로 자기를 등록한다. 모듈이 없거나 import 뒤에도 이름이 없으면 `UnknownImplError` (11/19 결정).
- `embed`(글 → 벡터)는 부르는 쪽(채점기, F2·F3)이 `core/llm`의 `embed()`를 넘기고, 구현은 `(repo, settings, embed)`로 만들어진다. `retrieval`은 `core`를 import하지 않으므로 모델 호출을 직접 하지 않는다 (11/19 리뷰). fake는 녹화 파일을 읽는 `recorded_embed(path)`를 받는다 (`settings["query_vectors"]`만 있어도 같은 녹화를 읽는다).
- `hybrid`를 넣기로 하면 인터페이스는 그대로 두고, 구현과 래퍼의 막는 줄만 바꾼다.
- 같은 점수의 순서는 `chunk_id` 오름차순이다 (다시 돌려도 같은 순서).

**맞음 판정 인터페이스** (`eval/retrieval/matchers.py`)
```python
# SearchHit은 Chunk 칸을 다 가지므로 그대로 넘김
class Matcher(Protocol):
    def matches(self, chunk: Chunk, item: GoldItem, row: GoldRow) -> bool: ...


MATCHERS: dict[Corpus, Matcher]  # "cite": CiteMatcher, "law": LawMatcher
```

**정답 파일** `data/goldsets/tune/retrieval/gold.jsonl` (git 밖, 한 줄 = 정답 줄 하나)
```json
{"row_id": "<발송번호>:r1:c1:KR20190012345A", "corpus": "cite",
 "query": "<OA 당시 청구항 1 전문>", "doc_ids": ["KR20190012345A"], "as_of": null,
 "items": [{"kind": "paragraph", "start": 22, "end": 25, "label": "[0022]-[0025]"},
           {"kind": "figure", "figures": [3], "label": "도 3"}],
 "exclude": null}
```
- 정답 항목의 `start`·`end`는 5-1 정렬 키와 같은 인코딩이다. 칼럼:줄 `3:10-25`는 `start: 30010, end: 30025`이고, 칼럼을 넘는 `3:50-4:5`는 `start: 30050, end: 40005`다.
- 법령 정답 줄 예시:
```json
{"row_id": "<발송번호>:r1", "corpus": "law",
 "query": "<#66이 정한 질의>", "doc_ids": null, "as_of": "2020-05-04",
 "items": [{"kind": "page", "start": 3203, "end": 3204, "label": "3203~3204쪽",
            "gold_edition": {"status": "confirmed", "effective_from": "2020-01-01"}}],
 "exclude": null}
```
  (`doc_ids: null` = 법령 말뭉치 전체에서 기준일로만 거름. 법령 `doc_id` 값과 `items` 단위는 #66이 정한다.)
- `row_id`: 내용으로 정함. 법령 `<발송번호>:r<거절이유 순번>`, 인용문헌 `<발송번호>:r<거절이유 순번>:c<청구항>:<공보 번호>` (11/19 리뷰, 조문 대신 순번: 같은 조문의 거절이유가 한 OA에 둘 이상일 수 있다). 꼴이 틀리거나, 인용문헌 줄의 공보 번호가 `doc_ids`에 없으면 정답 파일 읽기에서 멈춘다. 발송번호가 들어가므로 git에 넣는 파일(`scores.json`)에는 쓰지 않는다.
- `items[].gold_edition`(법령 항목만): `{"status": "confirmed", "effective_from": "2020-01-01"}` 또는 `{"status": "unverified"}`. 한 줄에 특허법 조문과 심사기준 쪽처럼 판본이 다른 항목이 같이 오므로 줄이 아니라 항목마다 둔다 (11/19 리뷰). 변환 스크립트가 `as_of`(OA 발송일)로 채운다. 항목 하나라도 확인되지 않음이면 그 줄을 빼고 `excluded_edition_unverified`에 센다 (항목만 빼면 Recall 분모가 바뀐다). 인용문헌 항목에는 두지 않는다.
- `exclude`: `null` / `no_location` / `clarity` / `same_as_other`. 변환 스크립트가 정한다.
- `items[].kind`: `paragraph` / `column_line` / `figure` / `claim` / `abstract` / `article` / `page`.
- 정답 세트 버전은 기존 규칙대로 `data/goldsets/VERSION`(정수)이다.

**채점기** `eval/retrieval/score.py`
- 명령: `uv run python -m eval.retrieval.score --config experiments/<실험>/config.yaml [--goldsets-root data/goldsets] [--chunks <조각 jsonl>] [--scores-dir <폴더>] [--cq-dir <폴더>]`.
  - `--goldsets-root`: 정답 세트 뿌리 (기본 `data/goldsets`). `VERSION`과 `<goldset>/` 폴더 검사를 이 아래에서 한다. 테스트는 임시 폴더에 같은 구조를 만들어 넘긴다.
  - `--chunks`: 주면 그 JSONL로 `InMemoryChunkRepository`를 만든다. 없으면 `PostgresChunkRepository`(`DATABASE_URL`)다.
  - `--scores-dir`, `--cq-dir`: 출력 폴더 (기본 `experiments/<실험>/`, `work/retrieval/<실험>/`).
  - **`--chunks`로 돌리면 출력은 `work/retrieval/<실험>/` 아래로만 간다.** `--scores-dir`의 기본값도 `work/retrieval/<실험>/`로 바뀐다. `experiments/` 아래를 주면 실행 전에 멈춘다 (가짜 조각 점수가 실험 표 `experiments/index.md`에 섞이지 않게).
  - 종료 코드: 성공 0, `RetrievalEvalError`(실행 전 검사, 남은 줄 0개, 색인 판 섞임, 줄 검색 예외) 1.
  - 함수 모양: `score(cfg, repo, goldsets_root, commit) -> ScoreReport`. CLI `main(argv, commit: str | None = None) -> int`가 저장소를 고르고 파일을 쓴다. `commit`이 None이면 `git rev-parse HEAD`, 실패하면 `"unknown"` (테스트는 값을 넘김). 채점기를 만드는 구현 task에서 이 명령을 루트 CLAUDE.md "채점 명령" 줄에 더한다 (명령이 생기기 전에는 적지 않음).
- 실험 설정 (기존 `experiments/_template/config.yaml`에 더하는 키):
```yaml
corpus: cite
index_version: cite-idx-v1
mode: bm25
impl: fake
k: [1, 3, 5, 10]
gold: retrieval/gold.jsonl          # <goldsets_root>/<goldset>/ 기준 상대 경로 (기본이면 data/goldsets/tune/retrieval/gold.jsonl)
law_location_rule: overlap_or_label   # 법령만. 생략하면 이 기본값 (7-4)
```
- `scores.json`: 기존 `experiments/_template/scores.schema.json` 모양을 따른다.
  - `metrics`: `hit@k`, `recall@k`, `random_hit@k`, `random_recall@k`, `recall_ratio@k`(k마다).
  - `failures`: 정해진 이름만 쓴다. `excluded_no_location`, `excluded_clarity`, `excluded_same_as_other`, `excluded_body_missing`, `excluded_edition_unverified`, `excluded_no_edition_in_scope`, `excluded_gold_not_in_scope`, `excluded_gold_items_not_in_scope`, `cq_candidates`, `recall_ratio_undefined`.
  - 위 표에 더하는 칸: `corpus`, `index_version`, `index_fingerprint`, `mode`, `impl`, `metric_name: "심사관 지정 위치 회수율"`, `gold_sha256`.
  - `index_fingerprint`: 그 색인 판 조각 전체의 `{"chunks": 조각 수, "chunk_ids_sha256": …}`. `make index-dump`의 `.fingerprint.json`과 같은 계산이다 (5-2). **지문이 다른 실험끼리는 점수를 비교하지 않는다** (색인 판 이름이 같아도 내용이 다르다).
  - 필수 칸 채우는 법: `experiment` = 설정 `experiment`, `commit` = `main`의 `commit` 인자 (위 함수 모양), `n` = 점수에 넣은 줄 수, `cost` = 이 채점기는 모델 호출이 없어 `seconds`만 채우고 나머지는 0.
  - 줄 ID·질의·정답 위치는 넣지 않는다.
- **E (정답 파일 버전 기록)**: `scores.json`의 `goldset_version`(`data/goldsets/VERSION` 정수)과 `gold_sha256`(정답 파일 해시)으로 남긴다. CQ 후보 줄마다 같은 두 값을 넣는다. 버전이 같아도 해시가 다르면 다른 정답으로 보고, CQ 모으기는 멈춘다.

**CQ 후보 파일** `work/retrieval/<실험>/cq_candidates.jsonl` (git 밖)
```json
{"row_id": "…", "goldset_version": 1, "gold_sha256": "…", "corpus": "cite", "impl": "fake", "mode": "bm25",
 "index_version": "cite-idx-v1", "k": 10, "query": "…", "items": [ … ],
 "found": [{"chunk_id": "…", "label": "[0031]", "score": 1.2}], "why": ""}
```

- 평가 세트·지표: `data/goldsets/tune/` v`VERSION` (git 밖), 지표 "심사관 지정 위치 회수율"(Hit@k·Recall@k). 문턱은 이 이슈에 없다 (계약). 문턱은 #66·#67 기준선을 잰 뒤 정한다.
- 데이터: 이 이슈는 지어낸 fixture만 쓴다 (9절).
- 실행 상한(비용·시간): 이 이슈에는 모델·외부 호출이 없다. 진짜 구현의 상한 키는 #66·#67 설정 `budget.max_external_calls`·`budget.max_usd`(기존 틀)다.
- 결과에 남길 것: `impl`, `mode`, `index_version`, `goldset_version`, `gold_sha256`, 커밋 해시. 모델 이름은 진짜 구현의 `settings`에 있다.

### 7-2. 각자 칸
- 재아: `fake` 구현 하나 (`src/patent_ai/retrieval/fake.py`). 진짜 검색이 아니라 계약을 테스트하려는 것이다.
  - `bm25` 모드: 공백으로 자른 낱말이 질의와 겹치는 수를 점수로 쓴다.
  - `vector` 모드: fixture의 조각 벡터와, 질의 문자열 → 벡터 녹화 파일(`query_vectors.json`)의 코사인 유사도를 쓴다. 녹화에 없는 질의면 `RecordedEmbeddingMissing` 오류를 낸다 (네트워크로 가지 않음).
- 모델 호출: 없음.
- 프롬프트 파일: 없음.
- 실험 설정(config): 위 7-1 키.

### 7-3. 계산식 (requirements 기준 3)
- 줄의 검색 범위 N = 그 색인 판에서 `doc_ids`·`as_of`로 거른 조각 수. k' = min(k, N).
- 항목 i에 맞는 조각 집합 Mᵢ (범위 안 조각 중 `Matcher`가 맞다고 한 것).
- 줄 Hit@k = 상위 k' 안에 어느 항목이든 맞는 조각이 있으면 1.
- 줄 Recall@k = 맞은 항목 수 / 항목 수.
- 무작위 (고르게 k'개 뽑기, 계산식):
  - P(항목 i 맞음) = 1 − C(N − |Mᵢ|, k') / C(N, k')
  - 줄 무작위 Recall@k = 항목 평균
  - 줄 무작위 Hit@k = 1 − C(N − |∪Mᵢ|, k') / C(N, k')
- 보고값 = 점수에 넣는 줄의 평균. `recall_ratio@k = 평균 Recall@k / 평균 무작위 Recall@k`. 분모가 0이면 그 k의 `recall_ratio@k` 키를 빼고 `failures.recall_ratio_undefined`에 1을 더한다 (기존 `scores.schema.json`의 `metrics`는 숫자만 받음). #129 뒤로는 Mᵢ = 0인 항목을 먼저 빼서 남는 항목이 모두 Mᵢ ≥ 1이라 분모가 0이 되지 않는다. `recall_ratio_undefined`는 사실상 늘 0이고, 방어용으로 키와 갈래만 남긴다.
- 점검 예 (fixture로 테스트): N = 10, 항목 2개(`[0022]-[0025]` → M₁ 4개, `도 3` → M₂ 1개), k = 5.
  - 무작위 P₁ = 1 − C(6,5)/C(10,5) = 1 − 6/252 = 0.976
  - 무작위 P₂ = 1 − C(9,5)/C(10,5) = 1 − 126/252 = 0.5
  - 무작위 Recall@5 = 0.738
  - 무작위 Hit@5 = 1 − C(5,5)/C(10,5) = 1 − 1/252 = 0.996 (∪M = 5개)
  - 상위 5개 중 `[0023]`만 맞으면 Hit@5 = 1, Recall@5 = 0.5, 배수 = 0.68
- 질의 누출 검사: 항목 종류마다 표기 패턴을 만들어 질의에서 찾는다.
  - 문단: `[0023]` 대괄호 형태만 (범위면 그 안 번호 전부). 맨 숫자 `0023`은 소수 "0.0023 중량%"와 구별할 수 없어 보지 않는다.
  - 도면: `도 3`·`도3`·`FIG. 3`·`Fig.3`
  - 조문: `제29조 제2항`·`29조 2항`
  - 칼럼:줄: `col. 3, l. 10`·`칼럼 3`처럼 앞말이 있을 때만 본다. 맨 `3:10`은 비율 "중량비 3:10"과 구별할 수 없어 보지 않는다.
  - 청구항·요약 항목은 검사하지 않는다. 질의 자신의 "제1항에 있어서"와 구별할 수 없어서다. 이 한계는 8절에 적는다.
  - 경계 조건 (평소 청구항 글자에 걸리지 않게):
    - 도면: `도` 앞이 문장 시작·공백·문장부호여야 한다("온도 300℃", "각도 30°", "농도 3%"의 `도`는 앞이 한글이라 안 걸림). 번호 뒤에 숫자·`.`(소수)·`℃`·`%`·`°`가 오면 안 된다. `도면 3`도 같은 규칙.
    - 조문: `제29조`처럼 `조` 글자까지 맞아야 한다.
  - 출원 쪽 도면 부호 `(110)`는 위 패턴에 걸리지 않는다.
  - fixture에 "온도 300℃", "0.0023 중량%", "중량비 3:10"이 든 질의 줄(모두 통과)을 둔다.

### 7-4. 맞음 판정 규칙 (requirements 기준 4)
- `CiteMatcher`:
  1. 조각 `doc_id`가 줄의 `doc_ids` 안이어야 한다. 아니면 틀림.
  2. `paragraph`·`column_line`·`page` 항목: 같은 `loc_kind`이고 [loc_start, loc_end]와 [start, end]가 겹치면 맞음.
  3. `figure` 항목: 조각 `loc_figures`가 항목 도면 번호와 하나라도 겹치면 맞음. 보통 `chunk_kind = figure_desc`이지만, 본문 조각이 도면 번호를 담고 있어도 맞음으로 본다 ("그 도면 설명을 담고 있으면", #9 B-3).
  4. `claim` 항목: `loc_claims`가 겹치면 맞음. `abstract` 항목: `chunk_kind = abstract`면 맞음.
  5. 2번에서 조각이나 항목의 정렬 키가 null이면 `loc_label` 글자가 같을 때만 맞음 (`LawMatcher` 기본값과 같은 규칙).
  6. 공보가 다르면(같은 출원의 공개 `A`만 색인에 있고 정답은 등록 `B`) 1번에서 거른 문헌 조각이 0개가 된다. 그러면 검색 결과가 `body_missing`이고 그 줄은 빠진다 (판단은 2절 4번 한 곳).
- `LawMatcher`:
  1. 조각 `edition_status = confirmed`이고 시행 기간이 그 정답 항목 `gold_edition.effective_from`과 같은 법령 판본이어야 한다 (항목마다 본다).
  2. 위치 규칙은 #66이 끼우는 함수 `(chunk, item) -> bool`이다. `register_law_location_rule("<이름>")`으로 등록하고 실험 설정 `law_location_rule: <이름>`으로 고른다 (`impl`과 같은 방식, `matchers.py`는 안 고침). 설정에 없으면 `overlap_or_label`을 쓴다. 이 기본값은 "같은 `loc_kind`이고 정렬 키가 겹침"이고, 정렬 키가 null이면 `loc_label` 글자가 같을 때만 맞음이다.

### 7-5. CQ 모으기 (requirements 기준 5)
- `uv run python -m eval.retrieval.cq_merge <파일>… -o work/retrieval/cq_merged.jsonl`
- 모든 파일에 있는 `row_id`만 남긴다 (교집합). 파일끼리 `goldset_version`이나 `gold_sha256`가 다르면 멈춘다. 결과가 0건이면 경고한다.

## 8. 이 기능 안의 결정
| 고른 것 | 버린 것 | 이유 | 계기 (설계 / 구현 중 문제) | 근거 (실험 폴더, troubleshooting) |
|---|---|---|---|---|
| 말뭉치마다 표 (`law_chunks`, `cite_chunks`), DB 하나 | 표 하나 + 행 단위 덤프 / 검색용 DB 따로 / 색인 판마다 표 | `index-load`(`pg_restore --clean`)가 표를 통째로 바꾸는데, 말뭉치마다 만드는 사람이 한 명이라 잃는 게 없고 기존 명령을 그대로 씀. DB 하나는 ADR 0003 확정 | 설계 (11/18 인터뷰) | Makefile 49줄, PostgreSQL 공식 문서 pg_restore |
| 벡터 칸 길이 안 정함, 인덱스 없음 | 길이 고정 + HNSW / 임베딩 별도 표 | 임베딩 모델 비교 실험 동안 길이가 다른 색인 판이 한 표에 같이 있음. 우리 양에선 다 비교해도 됨 [가정 5] | 설계 | pgvector README (오픈소스) |
| `hybrid`는 이름 자리만 | 공통 RRF 구현 / 빼기 | PRD·#66·#67 합격 기준에 없음. CQ는 BM25·벡터 각각 결과로 정해짐. 자리가 있으면 나중에 넣어도 인터페이스 안 바뀜 | 설계 | product.md 126줄 |
| 정답 파일 모양을 #65가 정함 | 은진 님 파일 그대로 / 둘이 새로 | 가짜 fixture로 바로 테스트, 변환은 스크립트 하나 | 설계 | |
| 공통 계산 + 말뭉치별 `Matcher` | 판정 규칙 하나 | 인용문헌(문단·도면·공보)과 법령(판본·조항)의 "맞음"이 다름. 계산은 같음 | 설계 (11/18 사용자 지적) | #9 B-3 |
| 인용문헌 질의 = OA 당시 청구항 전문 | 구성요소별 / OA 문단에서 번호 가림 | 지금 있고 정답이 새지 않음 | 설계 | product.md 6절 F3 |
| 법령 정답 판본 = OA 발송일 시행판 | 판본 무시 줄도 / #66에 미룸 | #9 B "판본까지 맞아야 맞음" | 설계 | |
| 검색 결과 스키마를 `retrieval/schemas.py`에 | `core/schemas/` | `retrieval`이 `core`를 import하면 부르는 방향이 거꾸로 됨 | 설계 | ADR 0003 폴더 |
| 누출 검사에서 청구항·요약 항목 제외 | 전부 검사 | 질의 자신의 "제1항에 있어서"와 구별 불가. 한계로 남김 | 설계 (doc-review 2회차) | |
| 저장소는 `retrieval/`, ORM은 `db/`, `retrieval → db` 방향 추가 | 저장소를 `db/`에 | 검색 계약과 거르기 규칙을 한곳에. `db`는 표 정의만 | 설계 (design doc-review, 11/18 허용) | ADR 0003 폴더 |
| 공통 검사는 `get_searcher`가 감싸는 래퍼 `CheckedSearcher` | 구현마다 검사 | #66·#67이 빠뜨릴 수 있음 | 설계 (plan-reviewer, 11/18) | |
| `--chunks`(메모리)로 돌리면 출력은 `work/`만 | 어디든 씀 | 가짜 조각 점수가 실험 표에 섞이지 않게 | 설계 (plan-reviewer, 11/18) | |
| 기준일로 범위 조각이 0개인 줄은 빼고 셈 (`excluded_no_edition_in_scope`) | 채점 전체를 멈춤 / Hit 0으로 셈 | 줄 하나 때문에 tune 점수가 안 나오지 않게. N=0이면 무작위 기준선을 못 정함 | 구현 중 문제 (11/19) | |
| 범위 안에 정답 조각이 0개인 항목은 빼고 셈, 모두 0개면 줄째 (`excluded_gold_items_not_in_scope`·`excluded_gold_not_in_scope`), 법령·인용문헌 둘 다 | Hit 0으로 셈 / 항목 하나라도 0이면 줄째 / 법령만 | 데이터 문제가 Hit@k를 내리고 CQ에 섞임. 줄째 빼면 다른 항목으로 맞힌 줄까지 빠짐. 인용문헌도 같은 상황이라 같이 (재아 요청) | 구현 중 문제 (#129, #121 리뷰) | 이슈 #129 |
| `get_searcher`가 `impl` 이름으로 구현 모듈을 import | `retrieval/__init__`에 구현 목록 / 설정에 `impl_module` | #66·#67이 계약 파일을 안 고치고 새 파일만 더함 | 구현 중 문제 (11/19) | |
| 이슈 셋으로 나눔 (A1·A2·B) | 둘 (A·B) | A가 400줄 규칙을 넘음. B·#66·#67은 A1만 필요 | 설계 (plan-reviewer, 11/18) | |
| 법령 조각 = 항 단위 (호·목은 항 안, 앞에 조 제목). 항 없는 조는 조 하나 | 조 단위 / 호 단위 | 정답이 모두 항까지 있고 29조 1항(신규성)·2항(진보성)을 나눔. 호 단위는 글이 짧아 BM25가 약함 | 설계 (#66, 11/19) | 이슈 #66 본문 |
| 법령 위치 번호 = 조×10000 + 가지×100 + 항 (29조 2항 = 290002) | 조×100+항 / 이름표만 | 가지조문(52조의2)이 겹치지 않음. 기본 `overlap_or_label` 규칙 그대로 (정답 29조1항2호 → 290001) | 설계 (#66) | |
| 법령 판본 = 파일 시행일부터 같은 법 다음 판 시행일 전날까지, 마지막 판은 끝 없음. 시행일 순(번호 순 아님). 시행일 못 읽으면 unverified | 시작일만 / 공포일 | 기준일로 판 하나만 걸림. 222497(2020-10-20)이 219103(2020-12-10)보다 먼저 | 설계 (#66) | |
| 법령 `doc_id` = 원본 파일 이름 (`특허법_212229_20200311`, `특허법_시행령_…`) | 법령 이름만 | 같은 번호(MST)에 시행일이 둘인 판이 있음. 정답 적용판본과 같은 모양 | 설계 (#66) | |
| 법령 질의 = OA `[구체적인 거절이유]` 본문을 순번별로 자르고 조문 표기를 `[조문]`으로 가림. 끝은 `[첨 부]`·`<< 안내 >>`·심사관 서명 줄 | 본문 전체 하나 / 사람이 자름 | 줄마다 다른 거절이유. 순번이 정답과 안 맞으면 사건째 빼고 셈. 서명 이름을 질의에 넣지 않음 | 설계 + 구현 중 문제 (#66) | |
| 법령 정답 파일 `retrieval/law_gold.jsonl` (인용문헌과 따로) | `gold.jsonl` 하나 | 채점기가 다른 말뭉치 줄이 섞이면 멈춤 | 구현 중 문제 (#66) | |
| `law_bm25`: Okapi BM25, 두 글자 낱말, 통계는 그 검색 범위(기준일 판) 안에서 | 공백 낱말 / 형태소 분석기 / 전체 판 통계 | 조사·줄바꿈에 덜 흔들리고 의존성 없음. 옛 판이 idf를 흔들지 않음 | 설계 (#66) | experiments/m2-i1-law-bm25-baseline |
| 넣기는 `retrieval/law_index_db.py` (이번 판 줄만 한 트랜잭션으로 다시 씀). 그 판이 DB에 있으면 내용 해시가 같을 때만 | `db/`에 / `make index-load` / 있으면 무조건 멈춤 | `db`는 `retrieval`을 import하지 않음. 공유 DB라 다른 판·표는 안 건드림. 같은 판 이름에 다른 내용이면 덤프 받은 쪽과 어긋나서 새 판으로 | 구현 중 문제 (#66, 리뷰 11/19) | |
| 법령 벡터 색인 = 새 판 `law-idx-v2` (v1 조각 그대로 + `embedding`). 심사기준은 `law-idx-v3` | v1에 벡터만 채움 / 벡터를 DB 밖 파일로 | v1 덤프를 이미 공유했고 "설정을 바꾸면 새 판" 규칙. v2에서 BM25를 다시 돌려 v1과 점수가 같음을 확인 | 설계 (#66, 11/19) | experiments/m2-i2-law-vector-baseline |
| 임베딩 모델 = OpenAI `text-embedding-3-small` (기준선), 설정 `config/law_search.yaml` | 3-large / 로컬 모델 | 싸고(고유 글 1,142개 + 질의 19개 $0.0046) 비교는 설정만 바꿔서. 로컬 모델은 torch 같은 의존성 | 설계 (#66, 11/19) | |
| 같은 글은 한 번만 임베딩 (`core/index_embed`) | 조각마다 | 법령은 판마다 같은 조문이 많아 조각 10,649개에 고유 글 1,142개 | 구현 중 문제 (#66) | |
| `vector` 검색기는 말뭉치를 안 가리고, 질의 벡터는 `settings.query_vectors` 파일로 받아 채점기를 안 고침 | 채점기에 embed 넘기기 | 공용 채점기를 바꾸지 않고 fake와 같은 길. 질의 벡터는 `eval/retrieval/embed_queries`로 미리 만들어 git 밖에 (정답 파일은 채점기 쪽만 읽음) | 설계 (#66) | |
| `vector`는 점수 문턱 없이 범위 안 조각을 다 순위 매김 (`fake`·`law_bm25`는 점수 0 이하를 뺌) | 코사인 문턱 | 문턱은 기준선을 잰 뒤 정하기로 함 (이 문서 2절). 그래서 범위 안 조각이 있으면 `not_found_in_scope`가 사실상 안 나옴: F2가 쓸 때 "못 찾음 ≠ 없음"을 문턱으로 다시 볼 것 | 리뷰 (#66, 11/19) | |

- ADR 세 조건을 다 맞는 결정은 없다고 본다. 표 나누기는 되돌릴 때 마이그레이션 하나와 덤프 다시 뽑기라 "되돌리기 어렵다"가 약하다.

## 9. 테스트 방법
- 어디서 테스트하나: 가장 바깥 경계 두 곳이다. `get_searcher(...).search(...)`(검색 계약)와 `score(config) -> 결과 객체`(채점기 CLI가 부르는 함수).
- 가짜 응답 / 녹화 응답 (`tests/fixtures/retrieval/`, 지어낸 자료만):
  - `chunks_cite.jsonl`: 공보 두 개 (`KR…A` 문단 10개 + 도면 설명 + 요약 + 청구항, `US…B2` 칼럼:줄 조각 몇 개)
  - `chunks_law.jsonl`: 같은 조문의 두 법령 판본 + `unverified` 조각 하나
  - `query_vectors.json`: 질의 → 벡터 녹화
  - `chunks_check.jsonl`: 7-3 점검 예용 공보 하나 (조각 정확히 10개)
  - 정답 파일은 목적마다 나눈다: `gold_ok.jsonl`(점검 예 줄만, 점수 기대값 테스트용), `gold_excluded.jsonl`(빼는 줄 이유마다 하나 + 종속항·"온도 300℃" 등 통과 질의), `gold_leak.jsonl`(누출 줄), `gold_empty.jsonl`(0줄), `gold_all_excluded.jsonl`(모두 빠지는 줄)
  - `config_*.yaml`: 맞는 색인 판, 없는 색인 판, 없는 `impl`
  - 계산식은 순수 함수(`random_recall(10, [4, 1], 5)` 등)로 따로 테스트하고, 소수는 `pytest.approx(abs=1e-3)`로 비교한다.
- 상태·경우마다 하나씩:
  - 결과 있음 (`status: null`)
  - `not_found_in_scope`
  - `unverified(body_missing)`
  - 기준일 거르기와 `skipped_unverified_edition`
  - `hybrid` → `ModeNotSupportedError`
  - 없는 `impl` → `UnknownImplError`
  - 색인 판 없음·섞임 → 실패
  - 정답 0줄 → 실패, 남은 줄 0개 → 실패 (종료 코드 1)
  - `--chunks`로 돌리며 `--scores-dir`이 `experiments/` 아래 → 실행 전 실패
  - `--cq-dir`이 git 안 경로(무시되지 않음) → 실행 전 실패
  - 누출 → 실패, 종속항 → 통과
  - CQ 0건 경고
  - CQ 모으기: 교집합, 버전 다름 → 멈춤
  - `scores.json`에 `row_id`·질의 글자가 없음, 실패·경고 메시지에 질의 글자가 없음 (`row_id`는 있어도 됨)
- 실제 DB: `tests/test_retrieval_db.py` `@pytest.mark.db` 하나 (기준 7, 있으면 좋음). 마이그레이션 → 두 표에 조각 넣기 → `PostgresChunkRepository`로 색인 판·기준일 거르기.
- `pgvector` 파이썬 패키지의 SQLAlchemy 타입 `VECTOR(dim=None)`는 길이 없는 `vector`로 선언된다 (pgvector-python `pgvector/sqlalchemy/vector.py`, 오픈소스). 의존성 `pgvector`를 더한다.

## 10. 구현 나누기 (tasks.md 제안)
- 어림 900줄 안팎이라 이슈 계획 셋으로 나눈다 (한 PR 400줄 규칙). task는 /plan-feature에서 정한다.
  - A1. 검색 계약 코드: 스키마(`Chunk`·`SearchHit`·`SearchResult`), `Searcher`·등록표·`CheckedSearcher`, `ChunkRepository`·`InMemoryChunkRepository`, `fake` 구현과 fixture.
  - A2. DB: 조각 표 ORM·마이그레이션, `PostgresChunkRepository`, `index-dump`·`index-load`·revision 옆 파일.
  - B. 채점기: 정답 파일 읽기, 실행 전 검사·누출 검사, `Matcher` 둘, 계산식, `scores.json`, CQ 파일·모으기.
- 순서: **B와 이슈 #66·#67은 A1만 있으면 시작할 수 있다.** 계약 코드와 메모리 저장소로 개발·테스트하고, 실제 DB가 필요할 때 A2를 받는다. A2는 A1 뒤 언제든 B와 동시에 할 수 있다.
