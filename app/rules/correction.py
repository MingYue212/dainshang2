"""纠错规则（SPEC 12.4）：可纠正错误 → 中文反馈 SystemMessage，带全轨迹重跑。"""

from langchain_core.messages import SystemMessage

from app.errors import AgentExecutionError, AgentOutputValidationError, CorrectableErrorCode

_FEEDBACK: dict[CorrectableErrorCode, str] = {
    CorrectableErrorCode.MODEL_OUTPUT_INVALID: (
        "上一次回复不符合服务端要求的输出结构，请严格按约定结构重新回复。"
    ),
    CorrectableErrorCode.UNSUPPORTED_FACT: (
        "上一次回复未通过服务端校验：以下内容缺少工具结果支持——{detail}。"
        "无法确认的业务事实不要回答，请基于本轮工具结果重写。"
    ),
    CorrectableErrorCode.UNVERIFIED_ACTION_RESOURCE: (
        "上一次回复引用了未经核实的页面资源：{detail}。"
        "只能引用本轮已成功查询的资源。"
    ),
}


class OutputCorrectionRules:
    @staticmethod
    def can_correct(error: AgentOutputValidationError) -> bool:
        return isinstance(error.code, CorrectableErrorCode)

    @staticmethod
    def build_feedback(error: AgentOutputValidationError) -> SystemMessage:
        template = _FEEDBACK.get(error.code, _FEEDBACK[CorrectableErrorCode.MODEL_OUTPUT_INVALID])
        return SystemMessage(content=template.format(detail=error.detail))

    @staticmethod
    def can_correct_execution(error: AgentExecutionError) -> bool:
        """执行层错误一律不可纠正（终态），留接口只为语义完整。"""
        return False
