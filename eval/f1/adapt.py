"""OAResult(앱 결과) -> F1Pred(정답 꼴 예측). 채점기는 정답 꼴끼리 비교한다 (#20 Q1).

규칙 (#20 task 5):
- 확인됨(confirmed) 값만 '냈다'로 본다. 확인되지 않음·충돌은 '안 냄'(틀림, 지어낸 값 아님).
- 조문은 코드(`29-2`)가 아니라 원문 글자(raw_text)로 낸다 (정답의 article은 원문 글자).
- 인용은 거절이유마다 있으므로 라벨로 묶어 OA 한 장짜리 표로 만든다.
- 청구항·거절이유 번호를 모르거나 확인되지 않은 청구항 줄은 뺀다 (그 줄 칸은 다 틀림).
- 인용 없는 줄의 no_location(`위치 없음 (…)`)은 위치 채점에서 어차피 빠지므로 옮기지 않는다.
"""

import logging

from eval.f1.pred import (
    F1Pred,
    PCitation,
    PClaimRow,
    PClaims,
    PDate,
    PNoticeKind,
    PRejection,
    PTargets,
    PValue,
)
from patent_ai.core.schemas.common import ExtractedValue, StatusValue
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)


def _ok(v: ExtractedValue | None) -> bool:
    return v is not None and v.status.value == StatusValue.CONFIRMED


def _value(v: ExtractedValue | None):
    return v.value if _ok(v) else None


def _text(v: ExtractedValue | None) -> str | None:
    return v.raw_text if _ok(v) else None


def _page(v: ExtractedValue | None) -> int | None:
    return v.page if _ok(v) else None


def to_pred(oa: OAResult) -> F1Pred:
    def pv(v: ExtractedValue) -> PValue:
        # given: 확인됐을 때만 '냈다'. 값 None이 정답 '없음'과 맞음으로 세지지 않게
        return PValue(value=_value(v), text=_text(v), page=_page(v), given=_ok(v))

    def pclaims(v: ExtractedValue) -> PClaims:
        return PClaims(value=_value(v), text=_text(v), page=_page(v))

    rejections = []
    by_label: dict[str, dict] = {}  # 라벨 -> 인용 칸 (확인된 번호가 있는 거절이유 기준)
    for r in oa.rejections:
        article_ok = _ok(r.article)
        rejections.append(
            PRejection(
                no=r.no,
                # 종류·지원은 조문에서 규칙으로 정해지므로 조문이 확인됐을 때만 낸다
                kind=r.kind.value if article_ok else None,
                article=_text(r.article),
                supported=r.supported if article_ok else None,
                targets=PTargets(value=_value(r.claims), text=_text(r.claims)),
                page=_page(r.article) or _page(r.claims),
            )
        )
        for c in r.citations:
            entry = by_label.setdefault(
                c.label,
                {
                    "label": c.label,
                    "key": _value(c.number),
                    "text": _text(c.number),
                    "page": _page(c.number),
                    "rejections": [],
                },
            )
            if entry["key"] is None and _ok(c.number):
                # 앞 거절이유에서는 확인되지 않았고 여기서 확인됐으면 이쪽 번호를 쓴다
                entry.update(key=_value(c.number), text=_text(c.number), page=_page(c.number))
            elif _ok(c.number) and _value(c.number) != entry["key"]:
                # 앱은 같은 문헌에 같은 라벨을 준다. 다르면 앱 쪽 문제라 알린다
                # (번호 글자는 남기지 않는다)
                logger.warning("인용 %s: 확인된 번호가 둘 이상이다 (앞 것을 씀)", c.label)
            if r.no not in entry["rejections"]:
                entry["rejections"].append(r.no)

    rows = [
        PClaimRow(
            claim=row.claim,
            rejection=row.rejection,
            citations=row.citations,
            locations=row.locations,
            same_as=row.same_as,
            clarity_terms=row.clarity_terms,
            clarity_reason=row.clarity_reason,
            text=row.raw_text,
            page=row.page,
        )
        for row in oa.claim_rows
        if row.status.value == StatusValue.CONFIRMED
        and row.claim is not None
        and row.rejection is not None
    ]

    hints = oa.examiner_hints
    return F1Pred(
        application_number=pv(oa.application_number),
        dispatch_number=pv(oa.dispatch_number),
        notice_date=PDate(text=_text(oa.notice_date), page=_page(oa.notice_date)),
        response_due=PDate(text=_text(oa.response_due), page=_page(oa.response_due)),
        notice_kind=PNoticeKind(
            value=_value(oa.notice_kind),
            text=_text(oa.notice_kind),
            page=_page(oa.notice_kind),
        ),
        examined_claims=pclaims(oa.examined_claims),
        allowable_claims=pclaims(hints.allowable_claims),
        amendment_note=pv(hints.amendment_note),
        rejections=rejections,
        citations=[PCitation(**c) for c in by_label.values()],
        claim_rows=rows,
    )
