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


# 글 속 조문 꼴: `제29조제2항`, `제42조 제4항 제2호`, `29조 2항`, `제29조의2제1항`.
# 항까지 있어야 한다 (색인 조각이 항 단위라서, 항이 없으면 지어내지 않고 건너뛴다).
_REF_IN_TEXT = re.compile(
    r"(?<![0-9])제?\s*(?P<jo>[1-9][0-9]*)\s*조(?:\s*의\s*(?P<gaji>[1-9][0-9]*))?"
    r"\s*제?\s*(?P<hang>[1-9][0-9]*)\s*항(?:\s*제?\s*(?P<ho>[1-9][0-9]*)\s*호)?"
)
# 조문 바로 앞에 붙은 법 이름 (`특허법`, `실용신안법 시행령`, `시행규칙`)
_LAW_BEFORE = re.compile(r"(?P<law>[가-힣]+법)?\s*(?P<sub>시행령|시행규칙)?\s*$")


def article_refs_in_text(text: str) -> list[ArticleRef]:
    """질문 글 속 조문을 ArticleRef로. 법 이름이 없으면 특허법, 다른 법(시행령 포함)은 버린다.

    같은 조·가지·항은 처음 하나만 남긴다 (호만 다른 것도 같은 항 조각이라서).
    """
    refs: list[ArticleRef] = []
    seen: set[tuple[int, int, int]] = set()
    for m in _REF_IN_TEXT.finditer(text):
        before = _LAW_BEFORE.search(text[: m.start()])
        if before and (before["sub"] or (before["law"] and before["law"] != LAW)):
            continue  # 특허법 시행령·실용신안법 등: 우리 색인의 특허법 조문이 아니다
        jo, gaji, hang = int(m["jo"]), int(m["gaji"] or 0), int(m["hang"])
        if (jo, gaji, hang) in seen:
            continue
        seen.add((jo, gaji, hang))
        ho = int(m["ho"]) if m["ho"] else None
        label = f"{LAW} 제{jo}조" + (f"의{gaji}" if gaji else "") + f"제{hang}항"
        label += f"제{ho}호" if ho else ""
        refs.append(ArticleRef(law=LAW, jo=jo, gaji=gaji, hang=hang, ho=ho, label=label))
    return refs
