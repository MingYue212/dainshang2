"""全局枚举（SPEC 5.1）。"""

from enum import StrEnum


class RunState(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_CONFIRM = "AWAITING_CONFIRM"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ReplyType(StrEnum):
    ANSWER = "ANSWER"
    CLARIFY = "CLARIFY"
    DECLINE = "DECLINE"
    REQUEST_HANDOFF = "REQUEST_HANDOFF"


class FailureType(StrEnum):
    BUSINESS = "BUSINESS"
    SERVICE_CALL = "SERVICE_CALL"
    CONTRACT = "CONTRACT"


class SkillCode(StrEnum):
    PRODUCT = "PRODUCT_SERVICE"
    ORDER = "ORDER_SERVICE"
    LOGISTICS = "LOGISTICS_SERVICE"
    REFUND = "REFUND_SERVICE"
    POLICY = "POLICY_FAQ"


class ToolCategory(StrEnum):
    BUSINESS = "BUSINESS"
    KNOWLEDGE = "KNOWLEDGE"
    GUIDANCE = "GUIDANCE"


# 允许的 Run 状态流转（SPEC 10 章，其他一律拒绝）
ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.RUNNING: {
        RunState.AWAITING_CONFIRM,
        RunState.COMPLETED,
        RunState.FAILED,
    },
    RunState.AWAITING_CONFIRM: {RunState.COMPLETED, RunState.SUPERSEDED},
}
_TERMINAL = {RunState.COMPLETED, RunState.FAILED, RunState.SUPERSEDED}


def transition_allowed(current: RunState, target: RunState) -> bool:
    if current in _TERMINAL:
        return False
    return target in ALLOWED_TRANSITIONS.get(current, set())
