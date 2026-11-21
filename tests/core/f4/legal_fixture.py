"""F4 테스트가 같이 쓰는 만든 값: 근거를 다 확인한 법률 근거 묶음 (F2 결과 모양)."""


def confirmed_legal(unit_id: str, rejection: int) -> dict:
    """F2가 근거를 다 확인한 법률 근거 묶음 (만든 값). 안쪽 표시가 비는 사건을 만들 때 쓴다."""
    source = {
        "source_kind": "statute",
        "identifier": "만든 조문",
        "evidence": {"document_id": "law_1", "raw_text": "만든 조문 글자", "edition": "2099-01-01"},
        "status": {"value": "confirmed", "checked": "원문 대조"},
    }
    claim = {
        "no": 1,
        "text": "만든 주장",
        "sources": [source],
        # review 없는 주장은 needs_human_review가 필수라 넣는다
        "review": {
            "verdict": "supported",
            "reason": "만든 검토 이유",
        },
        "status": {"value": "confirmed", "checked": "모든 근거 원문 대조"},
    }
    return {
        "bundle_id": f"lb:{unit_id}",
        "unit_id": unit_id,
        "oa_id": "oa_1",
        "rejection": rejection,
        "question": {
            "text": "만든 질문",
            "source": "oa_rejection",
            "as_of": None,
            "as_of_source": "none",
            "source_kinds": ["statute"],
        },
        "checked_on": "2099-02-01",
        "claims": [claim],
        "status": {"value": "confirmed", "checked": "모든 주장 근거 확인"},
    }
