---
name: 실험
about: 비교 실험 하나 (설정 값 하나 또는 각자 구현을 같은 평가 세트로 점수 비교)
title: "feat(ai): "
labels: ["실험"]
assignees: []
---

**가설**: <무엇을 바꾸면> <어느 점수가> <왜> 오를 것이다
**기준선**: experiments/<기준선 실험>/
**종류**: 설정 비교 / 구현 비교
**바꿀 것 (하나)**: `config.yaml`의 `<settings 키 또는 impl>`: <기준값> → <새 값>
**평가 세트**: goldsets/tune v<버전>
**예상 비용·호출 수**: 
**담당**: 

## 끝나면
- [ ] experiments/<실험>/card.md 채움 (점수, 실패 유형, 비용, 다음)
- [ ] 비교 회의에서 고름 → 고른 결과를 docs/features/<기능>/design.md에 한 줄
