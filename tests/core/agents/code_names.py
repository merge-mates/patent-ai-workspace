"""이유 글에 코드 이름이 섞였는지 보는 정규식 (이슈 #294). 테스트끼리 같이 쓴다."""

import re

# 코드 이름 모양: 소문자·밑줄 이어진 이름(read_oa, run_f3), 점으로 이은 이름(CaseInput.texts)
CODE_NAME = re.compile(r"[a-z_]{3,}|[A-Za-z]+\.[A-Za-z]+")
