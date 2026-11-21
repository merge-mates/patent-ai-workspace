---
실험: m2-i3-cite-search-hybrid-noise-c
기능: cite-search (이슈 #178 둘째 점수, C안)
담당: 은진
날짜: 2026-11-22
기준선: experiments/m2-i3-cite-search-bm25-noise-c/
평가 세트: tune v2
바꾼 것: `mode`·`impl`: bm25 → hybrid (같은 색인 cite-idx-v4·같은 C안 범위)
주 지표: hit@10
---
# 인용문헌 hybrid 둘째 점수 (노이즈 C안, 판 2)

결과 표·해석·다시 돌리기는 [m2-i3-cite-search-bm25-noise-c/card.md](../m2-i3-cite-search-bm25-noise-c/card.md)에 세 방식을 한 표로 모았다. 이 폴더는 그 표의 hybrid C 열 scores.json이다.
