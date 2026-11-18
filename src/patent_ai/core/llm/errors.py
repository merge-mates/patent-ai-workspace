"""모델 호출 오류. task-3에서 쓸 두 개는 이름만 먼저 둔다."""


class ModelConfigError(Exception):
    """설정 파일·단계·프롬프트 파일·프롬프트 변수 문제."""


class ModelOutputInvalid(Exception):
    """모델 답이 JSON이 아니거나 output_schema 검사에 떨어짐. 메시지에 이유."""


class ModelCallFailed(Exception):
    """전송 오류·429가 재시도 뒤에도 계속됨 (task-3에서 사용)."""


class ModelCallLimitExceeded(Exception):
    """호출 상한을 넘음 (task-3에서 사용)."""
