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
1. 입력: 실험 설정(`experiments/<실험>/config.yaml`), 정답 파일(`data/goldsets/tune/retrieval/gold.jsonl`), 조각 저장소(테스트는 메모리, 실제는 Postgres).
2. 실행 전 검사 (requirements 기준 3):
   - `index_version`이 그 말뭉치 표에 있는지
   - 정답 파일이 있고 1줄 이상인지
   - 질의에 그 줄 정답 위치 표기가 있는지 (7-3 누출 검사)
   - 설정의 `goldset_version`이 `data/goldsets/VERSION`과 같은지, `gold:` 경로가 `goldset:` 세트 폴더(`data/goldsets/<goldset>/`) 안인지. 정답 파일은 `gold:` 경로로 읽는다.
   - 하나라도 걸리면 `RetrievalEvalError`로 끝나고 종료 코드는 1이다.
3. 검색 전에 뺄 줄: `exclude` 칸이 있는 줄, 법령 정답 판본이 `unverified`인 줄. 뺀 줄은 이유별로 센다.
4. 줄마다 `search(query, corpus, mode, k=max(k 목록), doc_ids, as_of)`를 한 번 부른다. 작은 k는 같은 결과의 앞부분을 잘라 쓴다.
   - 본문 미확보는 여기서만 정한다: 결과 `status`가 `unverified`(`text_missing`)면 그 줄을 빼고 `excluded_text_missing`에 센다.
   - 결과에 다른 색인 판 조각이 있으면 실패로 끝난다.
5. 결과 조각마다 그 말뭉치 `Matcher`로 정답 항목과 맞는지 본다.
6. k마다 줄 Hit·Recall, 무작위 기대값을 계산한다 (7-3).
7. 결과 저장: `experiments/<실험>/scores.json`(모은 숫자), `work/retrieval/<실험>/cq_candidates.jsonl`(CQ 후보).
- 실패하면: 실행 전 검사가 막는다. 줄 하나의 검색이 예외를 내면 그 줄에서 멈추고 실패로 끝난다 (조용히 건너뛰지 않음).
- 비면: 검색 결과 0개는 `not_found_in_scope`이고, 그 줄은 Hit 0이며 CQ 후보가 된다. 거른 문헌 조각이 0개면 `unverified(text_missing)`이고 점수에서 뺀다. CQ 후보 0건이면 경고한다.
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
  "scope": {"doc_ids": ["KR1020190012345A"], "as_of": null, "k": 5},
  "status": null,
  "status_reason": null,
  "skipped_unverified_edition": 0,
  "hits": [
    {
      "chunk_id": "cite-idx-v1:KR1020190012345A:p0023",
      "doc_id": "KR1020190012345A",
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
- `status`는 결과가 비었을 때만 값이 있다: `not_found_in_scope`(찾아본 범위는 `scope`) 또는 `unverified`(`status_reason: "text_missing"`, 거른 문헌 조각이 0개).
- 결과가 있으면 `status`는 `null`이다. 조각은 근거 **후보**이고, "확인됨"은 뒤의 출처 확인 단계가 붙인다 ([architecture.md](../../architecture.md) 8절). 공통 속성은 [data-model.md](../../data-model.md) 3절 그대로 쓰고, 여기서 새로 정하는 값은 `status_reason: text_missing`, `edition.status: not_applicable`(인용문헌) 둘이다.
- 다시 확인 필요: 해당 없음 (검색은 저장하지 않는 도구 결과).
- 인터페이스 변경: 있음 (새로 생김). F2·F3 설계가 이 모양을 받는다. 스키마는 `src/patent_ai/retrieval/schemas.py`에 둔다. `core/schemas/`에 두지 않는 이유는 부르는 방향이 `core → retrieval`이라 `retrieval`이 `core`를 import하면 안 되기 때문이다 ([ADR 0003](../../decisions/0003-tech-stack.md) 폴더). data-model 4절 표에 "도구 결과" 줄로 이름을 더하는 것은 스키마 코드를 만드는 구현 task에서 한다.

## 4. 판과 근거
- 쓰는 청구항 판: 인용문헌 정답 줄의 질의 = OA 당시 청구항 전문. 어느 판인지는 정답 파일을 만드는 변환 스크립트가 출원번호 + 발송번호로 고른다 (#67). 이 계약은 질의 글자만 받는다.
- 쓰는 법령 판본: 정답 줄의 `as_of`(OA 발송일)로 `search`가 그날 시행 중인 법령 판본 조각만 거른다. 조각의 `edition.effective_from ≤ as_of ≤ effective_to`(끝이 없으면 현행). 법령 판본 상태가 `unverified`인 조각은 기준일 검색에서 빠지고 `skipped_unverified_edition`에 센다.
- 공보: 인용문헌 조각의 `doc_id`는 공보 번호(나라 + 번호 + 종류 코드, 예 `KR1020190012345A`, `US10123456B2`)다. 번호 정규화 규칙은 #67이 정하고, 이 계약은 같은 문자열끼리만 같다고 본다.
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
- 마이그레이션은 `CREATE EXTENSION IF NOT EXISTS vector`를 먼저 한다.
- 폴더: ORM 모델은 `src/patent_ai/db/models/chunks.py`, 인터페이스 `ChunkRepository`·`InMemoryChunkRepository`·`PostgresChunkRepository`는 `src/patent_ai/retrieval/repository.py`. 부르는 방향에 `retrieval → db`를 더한다. db는 retrieval을 import하지 않는다. ([ADR 0003](../../decisions/0003-tech-stack.md) 폴더 절에 같은 문장)
- 저장소 인터페이스 `ChunkRepository`(조각 읽기·셈)를 두고, 테스트는 `InMemoryChunkRepository`(fixture JSONL을 읽음), 실제는 `PostgresChunkRepository`(기준 7, 있으면 좋음)다. 둘 다 같은 거르기(색인 판·문헌·기준일)를 한다.

### 5-2. 덤프 ([db/CLAUDE.md](../../../src/patent_ai/db/CLAUDE.md) 검색 색인 절)
- `make index-dump CORPUS=law` → `pg_dump -Fc -t law_chunks` → `data/index/law-idx-<그 표의 가장 높은 색인 판>.dump`. 그 표의 모든 색인 판이 들어간다.
- 같은 이름 옆에 `law-idx-v1.revision`(만든 DB의 Alembic revision 한 줄)을 쓴다.
- `make index-load DUMP=…`는 옆 파일의 revision이 `alembic current`와 다르면 멈춘다 (기준 6, 있으면 좋음). 옆 파일이 없으면 경고만 하고 넣는다.
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

def get_searcher(impl: str, repo: ChunkRepository, settings: dict) -> Searcher  # 없는 이름 → UnknownImplError(쓸 수 있는 이름 목록)
```
- `Corpus = Literal["law", "cite"]`, `Mode = Literal["bm25", "vector", "hybrid"]`.
- `impl`은 이름 → 클래스 등록표(`register_impl("fake")`)로 고른다. #66·#67은 새 이름만 등록하고 이 파일들은 고치지 않는다.
- 어느 구현이든 `hybrid`를 부르면 `ModeNotSupportedError`다. 넣기로 하면 인터페이스는 그대로 두고 구현만 더한다.
- `k`는 1 이상이다. 같은 점수는 `chunk_id` 오름차순으로 순서를 정한다 (다시 돌려도 같은 순서).

**맞음 판정 인터페이스** (`eval/retrieval/matchers.py`)
```python
class Matcher(Protocol):
    def matches(self, hit: SearchHit, item: GoldItem, row: GoldRow) -> bool: ...
MATCHERS: dict[Corpus, Matcher]   # "cite": CiteMatcher, "law": LawMatcher
```

**정답 파일** `data/goldsets/tune/retrieval/gold.jsonl` (git 밖, 한 줄 = 정답 줄 하나)
```json
{"row_id": "<발송번호>:29-2:c1:KR1020190012345A", "corpus": "cite",
 "query": "<OA 당시 청구항 1 전문>", "doc_ids": ["KR1020190012345A"], "as_of": null,
 "gold_edition": null,
 "items": [{"kind": "paragraph", "start": 22, "end": 25, "label": "[0022-0025]"},
           {"kind": "figure", "figures": [3], "label": "도 3"}],
 "exclude": null}
```
- 정답 항목의 `start`·`end`는 5-1 정렬 키와 같은 인코딩이다. 칼럼:줄 `3:10-25`는 `start: 30010, end: 30025`이고, 칼럼을 넘는 `3:50-4:5`는 `start: 30050, end: 40005`다.
- 법령 정답 줄 예시:
```json
{"row_id": "<발송번호>:29-2", "corpus": "law",
 "query": "<#66이 정한 질의>", "doc_ids": null, "as_of": "2020-05-04",
 "gold_edition": {"status": "confirmed", "effective_from": "2020-01-01"},
 "items": [{"kind": "page", "start": 3203, "end": 3204, "label": "3203~3204쪽"}],
 "exclude": null}
```
  (`doc_ids: null` = 법령 말뭉치 전체에서 기준일로만 거름. 법령 `doc_id` 값과 `items` 단위는 #66이 정한다.)
- `row_id`: 내용으로 정함. 인용문헌 `<발송번호>:<조문>:c<청구항>:<공보 번호>`, 법령 `<발송번호>:<조문>`. 발송번호가 들어가므로 git에 넣는 파일(`scores.json`)에는 쓰지 않는다.
- `gold_edition`(법령): `{"status": "confirmed", "effective_from": "2020-01-01"}` 또는 `{"status": "unverified"}`. 변환 스크립트가 `as_of`(OA 발송일)로 채운다.
- `exclude`: `null` / `no_location` / `clarity` / `same_as_other`. 변환 스크립트가 정한다.
- `items[].kind`: `paragraph` / `column_line` / `figure` / `claim` / `abstract` / `article` / `page`.
- 정답 세트 버전은 기존 규칙대로 `data/goldsets/VERSION`(정수)이다.

**채점기** `eval/retrieval/score.py`
- 명령: `uv run python -m eval.retrieval.score --config experiments/<실험>/config.yaml`. 채점기를 만드는 구현 task에서 이 명령을 루트 CLAUDE.md "채점 명령" 줄에 더한다 (명령이 생기기 전에는 적지 않음).
- 실험 설정 (기존 `experiments/_template/config.yaml`에 더하는 키):
```yaml
corpus: cite
index_version: cite-idx-v1
mode: bm25
impl: fake
k: [1, 3, 5, 10]
gold: data/goldsets/tune/retrieval/gold.jsonl
law_location_rule: overlap_or_label   # 법령만. 생략하면 이 기본값 (7-4)
```
- `scores.json`: 기존 `experiments/_template/scores.schema.json` 모양을 따른다.
  - `metrics`: `hit@k`, `recall@k`, `random_hit@k`, `random_recall@k`, `recall_ratio@k`(k마다).
  - `failures`: 정해진 이름만 쓴다. `excluded_no_location`, `excluded_clarity`, `excluded_same_as_other`, `excluded_text_missing`, `excluded_edition_unverified`, `cq_candidates`, `recall_ratio_undefined`.
  - 위 표에 더하는 칸: `corpus`, `index_version`, `mode`, `impl`, `metric_name: "심사관 지정 위치 회수율"`, `gold_sha256`.
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
- 보고값 = 점수에 넣는 줄의 평균. `recall_ratio@k = 평균 Recall@k / 평균 무작위 Recall@k`. 분모가 0이면 그 k의 `recall_ratio@k` 키를 빼고 `failures.recall_ratio_undefined`에 1을 더한다 (기존 `scores.schema.json`의 `metrics`는 숫자만 받음).
- 점검 예 (fixture로 테스트): N = 10, 항목 2개(`[0022-0025]` → M₁ 4개, `도 3` → M₂ 1개), k = 5.
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
  5. 공보가 다르면(같은 출원의 공개 `A`만 색인에 있고 정답은 등록 `B`) 1번에서 거른 문헌 조각이 0개가 된다. 그러면 검색 결과가 `text_missing`이고 그 줄은 빠진다 (판단은 2절 4번 한 곳).
- `LawMatcher`:
  1. 조각 `edition_status = confirmed`이고 시행 기간이 정답 줄 `gold_edition.effective_from`과 같은 법령 판본이어야 한다.
  2. 위치 규칙은 #66이 끼우는 함수 `(hit, item) -> bool`이다. `register_law_location_rule("<이름>")`으로 등록하고 실험 설정 `law_location_rule: <이름>`으로 고른다 (`impl`과 같은 방식, `matchers.py`는 안 고침). 설정에 없으면 `overlap_or_label`을 쓴다. 이 기본값은 "같은 `loc_kind`이고 정렬 키가 겹침"이고, 정렬 키가 null이면 `loc_label` 글자가 같을 때만 맞음이다.

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

- ADR 세 조건을 다 맞는 결정은 없다고 본다. 표 나누기는 되돌릴 때 마이그레이션 하나와 덤프 다시 뽑기라 "되돌리기 어렵다"가 약하다.

## 9. 테스트 방법
- 어디서 테스트하나: 가장 바깥 경계 두 곳이다. `get_searcher(...).search(...)`(검색 계약)와 `score(config) -> 결과 객체`(채점기 CLI가 부르는 함수).
- 가짜 응답 / 녹화 응답 (`tests/fixtures/retrieval/`, 지어낸 자료만):
  - `chunks_cite.jsonl`: 공보 두 개 (`KR…A` 문단 10개 + 도면 설명 + 요약 + 청구항, `US…B2` 칼럼:줄 조각 몇 개)
  - `chunks_law.jsonl`: 같은 조문의 두 법령 판본 + `unverified` 조각 하나
  - `query_vectors.json`: 질의 → 벡터 녹화
  - `gold.jsonl`: 7-3 점검 예 줄, 빼는 줄(이유마다 하나), 누출 줄 하나, 종속항 질의 줄 하나
  - `config_*.yaml`: 맞는 색인 판, 없는 색인 판, 없는 `impl`
- 상태·경우마다 하나씩:
  - 결과 있음 (`status: null`)
  - `not_found_in_scope`
  - `unverified(text_missing)`
  - 기준일 거르기와 `skipped_unverified_edition`
  - `hybrid` → `ModeNotSupportedError`
  - 없는 `impl` → `UnknownImplError`
  - 색인 판 없음·섞임 → 실패
  - 정답 0줄 → 실패
  - 누출 → 실패, 종속항 → 통과
  - CQ 0건 경고
  - CQ 모으기: 교집합, 버전 다름 → 멈춤
  - `scores.json`과 실패·경고 메시지에 `row_id`·질의 글자가 없음
- 실제 DB: `tests/test_retrieval_db.py` `@pytest.mark.db` 하나 (기준 7, 있으면 좋음). 마이그레이션 → 두 표에 조각 넣기 → `PostgresChunkRepository`로 색인 판·기준일 거르기.
- `pgvector` 파이썬 패키지의 SQLAlchemy 타입 `VECTOR(dim=None)`는 길이 없는 `vector`로 선언된다 (pgvector-python `pgvector/sqlalchemy/vector.py`, 오픈소스). 의존성 `pgvector`를 더한다.

## 10. 구현 나누기 (tasks.md 제안)
- 어림 700줄 이상이라 이슈 계획 둘로 나눈다 (한 PR 400줄 규칙). 정할 곳은 /plan-feature.
  - A. 검색 계약: 스키마·`Searcher`·등록표·`fake`, 조각 표 마이그레이션·저장소, `index-dump`·revision 옆 파일. #66·#67이 색인을 만들려면 이것만 있으면 된다.
  - B. 채점기: 정답 파일 읽기, 실행 전 검사·누출 검사, `Matcher` 둘, 계산식, `scores.json`, CQ 파일·모으기.
