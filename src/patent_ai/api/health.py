from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """서버가 떠 있는지만 본다. DB 확인은 이슈 #55에서 더한다."""
    return {"status": "ok"}
