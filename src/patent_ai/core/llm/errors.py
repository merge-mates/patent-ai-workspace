"""모델 호출 오류."""


class ModelConfigError(Exception):
    """설정 파일·단계·프롬프트 파일·프롬프트 변수 문제."""


class ModelOutputInvalid(Exception):
    """모델 답이 JSON이 아니거나 output_schema 검사에 떨어짐. 메시지에 이유.

    stop_reason은 모델이 답을 끝낸 이유(모르면 None). truncated가 True면 답이 max_tokens에
    닿아 잘린 것이다 (모양이 틀린 답과 가르려고 둔다).
    """

    def __init__(self, message: str, stop_reason: str | None = None) -> None:
        super().__init__(message)
        self.stop_reason = stop_reason

    @property
    def truncated(self) -> bool:
        return self.stop_reason == TRUNCATED_STOP_REASON


# 출력 상한(max_tokens)에 닿아 답이 잘렸을 때 API가 주는 stop_reason 값
TRUNCATED_STOP_REASON = "max_tokens"


class ModelCallFailed(Exception):
    """전송 오류·429가 재시도 뒤에도 계속됨. 메시지에 마지막 이유."""


class ModelCallLimitExceeded(Exception):
    """호출 상한을 넘음. limit=어느 상한, used=쓴 양, limit_value=상한 값."""

    def __init__(self, limit: str, used: int, limit_value: int) -> None:
        super().__init__(f"{limit} 상한 {limit_value}을 넘음 (쓴 양 {used})")
        self.limit = limit
        self.used = used
        self.limit_value = limit_value


class RecordingMissing(Exception):
    """녹화한 답 파일이 없음. 조용히 진짜 호출하지 않고 멈춘다."""
