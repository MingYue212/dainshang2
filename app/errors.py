"""错误体系：可纠正（纠错循环重跑）与终态（Run 直接 FAILED）二分。"""

from enum import StrEnum


class CorrectableErrorCode(StrEnum):
    MODEL_OUTPUT_INVALID = "EC-1001"
    UNSUPPORTED_FACT = "EC-1002"
    UNVERIFIED_ACTION_RESOURCE = "EC-1003"


class TerminalErrorCode(StrEnum):
    MODEL_CALL_FAILED = "EC-2001"
    OUTPUT_VALIDATION_FAILED = "EC-2002"
    AGENT_EXECUTION_FAILED = "EC-2003"


type AgentErrorCode = CorrectableErrorCode | TerminalErrorCode


class AgentOutputValidationError(ValueError):
    """输出校验失败且可纠正——由纠错循环带反馈重跑。"""

    def __init__(self, code: CorrectableErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class AgentExecutionError(RuntimeError):
    """不可纠正的执行层异常——Run 直接置 FAILED。"""

    def __init__(self, code: TerminalErrorCode, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
