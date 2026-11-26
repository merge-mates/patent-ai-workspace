---
실험: m3-i2-oa-draft-judge-pilot
기능: F4
담당: 재아
날짜: 2026-11-25
기준선: 없음
평가 세트: tune 4건 (OA 파일럿 네 건)
바꾼 것: OA 논점별 의견서 초안 LLM 채점기 (논점 고정, 논점 응답·근거 지지 판정)
주 지표: 논점 직접 응답 수/전체 논점 수
---
# OA 의견서 초안 채점기 (재아 파일럿)

채점기 코드와 프롬프트만 있는 폴더다. 판정 기준은 [rubric.md](rubric.md), 프롬프트는 [response-prompt.md](response-prompt.md)·[support-prompt.md](support-prompt.md).
재아 님 브랜치 `codex/oa-draft-judge`에서 가져왔고, 원래 실행 기록·초안 원문·다시 돌리는 안내는 재아 님 로컬에 있다.
이 카드는 실험 표(`experiments/index.md`)가 폴더마다 카드 머리를 읽어서 은진이 더한 자리 표시다. 점수(`scores.json`)가 없어 표에는 "점수 없음"으로 나온다.
이 채점기를 은진 실험에서 쓴 결과는 [m3-i2-opinion-from-amend](../m3-i2-opinion-from-amend/card.md).
