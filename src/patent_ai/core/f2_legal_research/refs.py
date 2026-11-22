"""조문 코드·OA 발송일 꼴 맞추기 (design 7-1 `normalize_refs`의 OA 흐름 몫, 코드 도구).

- 조문 코드는 F1 `Rejection.article` 값(`29-2`, `29-1-1`, 호가 여럿이면 `29-1-1|29-1-2`).
- 색인 위치 번호는 법령 청커(`retrieval/law_index.article_loc`)와 같은 꼴: 조×10000 + 가지×100 + 항.
  호는 항 조각 안에 있어서 위치 번호에 들어가지 않는다.
- 발송일은 F1이 원문 글자만 둔다(`notice_date.value`는 비움). 여기서 날짜로 읽는다.
"""

import re
from dataclasses import dataclass
from datetime import date

from patent_ai.retrieval.law_index import article_loc

# 지금 F1이 내는 조문은 모두 특허법이다 (29조·42조, oa_result._KIND_BY_ARTICLE)
LAW = "특허법"

_CODE = re.compile(r"^(?P<jo>[1-9][0-9]*)-(?P<hang>[1-9][0-9]*)(?:-(?P<ho>[1-9][0-9]*))?$")
_DATE = re.compile(r"(?P<y>[0-9]{4})\s*[.\-/]\s*(?P<m>[0-9]{1,2})\s*[.\-/]\s*(?P<d>[0-9]{1,2})")


@dataclass(frozen=True)
class ArticleRef:
    """조문 하나 (법 이름 + 조·가지·항, 호는 표시용)."""

    law: str
    jo: int
    gaji: int
    hang: int
    ho: int | None
    label: str  # 사람이 읽는 표기 (`특허법 제29조제2항`)

    @property
    def loc(self) -> int:
        """색인 조각의 위치 번호 (항 조각)."""
        return article_loc(self.jo, self.gaji, self.hang)


def article_ref(code: str | None) -> ArticleRef | None:
    """F1 조문 코드 -> ArticleRef. 꼴이 다르거나 호들이 다른 항이면 None (지어내지 않는다)."""
    if not code:
        return None
    parts = [_CODE.match(p.strip()) for p in code.split("|")]
    if not all(parts):
        return None
    heads = {(int(m["jo"]), int(m["hang"])) for m in parts if m}
    if len(heads) != 1:
        return None  # 다른 조·항이 섞이면 조각 하나로 읽을 수 없다
    jo, hang = heads.pop()
    hos = [m["ho"] for m in parts if m]
    # 호가 하나일 때만 호까지 적는다. 여럿이면 그 항 전체를 가리킨다
    ho = int(hos[0]) if len(hos) == 1 and hos[0] else None
    label = f"{LAW} 제{jo}조제{hang}항" + (f"제{ho}호" if ho else "")
    return ArticleRef(law=LAW, jo=jo, gaji=0, hang=hang, ho=ho, label=label)


def parse_dispatch_date(raw: str | None) -> date | None:
    """발송일 원문 글자(`2020.05.04.`, `2020. 5. 4.`, `2020-05-04`) -> 날짜. 못 읽으면 None."""
    if not raw:
        return None
    m = _DATE.search(raw)
    if not m:
        return None
    try:
        return date(int(m["y"]), int(m["m"]), int(m["d"]))
    except ValueError:
        return None  # 없는 날 (2월 30일 등)
