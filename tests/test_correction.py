"""纠错反馈（FR-404）：可纠正/终态二分与反馈文案表（SPEC 12.4）。"""

from app.errors import (
    AgentExecutionError,
    AgentOutputValidationError,
    CorrectableErrorCode,
    TerminalErrorCode,
)
from app.rules.correction import OutputCorrectionRules


def test_can_correct_true_for_correctable():
    err = AgentOutputValidationError(CorrectableErrorCode.UNSUPPORTED_FACT, "金额 500")
    assert OutputCorrectionRules.can_correct(err) is True


def test_feedback_contains_detail():
    err = AgentOutputValidationError(
        CorrectableErrorCode.UNSUPPORTED_FACT, "缺少工具支持：[NUMBER] 500"
    )
    msg = OutputCorrectionRules.build_feedback(err)
    assert "缺少工具结果支持" in msg.content
    assert "[NUMBER] 500" in msg.content


def test_feedback_for_action_resource():
    err = AgentOutputValidationError(
        CorrectableErrorCode.UNVERIFIED_ACTION_RESOURCE, "ORDER_CARD 资源 A20260408002 未核实"
    )
    msg = OutputCorrectionRules.build_feedback(err)
    assert "未经核实的页面资源" in msg.content


def test_execution_error_never_correctable():
    err = AgentExecutionError(TerminalErrorCode.MODEL_CALL_FAILED, "timeout")
    assert OutputCorrectionRules.can_correct_execution(err) is False
