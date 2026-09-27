"""回答校验：事实检验（EC-1002）与失败降级（SPEC 12.3/12.5）。"""

from app.domain.enums import FailureType, ReplyType
from app.errors import AgentOutputValidationError, CorrectableErrorCode
from app.agent.output import AgentOutput
from app.harness.snapshot import ToolCallSnapshot
from app.rules.fact import FactChecker
from app.tools.registry import TOOL_CATALOG

UNVERIFIED_FACT_TEXT = "缺少工具支持：{facts}"
SERVICE_DECLINE_TEXT = "系统繁忙，请稍后再试，您可以随时回来继续。"


class AnswerValidator:
    checker = FactChecker()

    @classmethod
    def validate_facts(
        cls, output: AgentOutput, successful: tuple[ToolCallSnapshot, ...]
    ) -> None:
        """reply_type=ANSWER 时，回复中的业务事实必须有成功工具结果背书。"""
        unsupported = cls.checker.get_unsupported_facts(output.content, successful)
        if unsupported:
            detail = "、".join(f"[{f.category.value}] {f.value}" for f in unsupported)
            raise AgentOutputValidationError(
                CorrectableErrorCode.UNSUPPORTED_FACT,
                UNVERIFIED_FACT_TEXT.format(facts=detail),
            )

    @staticmethod
    def business_snapshots(snapshots: tuple[ToolCallSnapshot, ...]) -> list[ToolCallSnapshot]:
        return [
            s
            for s in snapshots
            if TOOL_CATALOG.get(s.tool_name) is not None
            and TOOL_CATALOG.get(s.tool_name).category  # type: ignore[union-attr]
            in (FailureType.BUSINESS.value,)  # ToolCategory.BUSINESS 与 FailureType.BUSINESS 同值 "BUSINESS"
        ]

    @classmethod
    def maybe_degrade(cls, output: AgentOutput, snapshots: tuple[ToolCallSnapshot, ...]) -> AgentOutput:
        """全部业务工具失败时的降级（SPEC 12.5）：
        全为 BUSINESS → 采用最后一条失败 message 作为回答；
        含 SERVICE_CALL/CONTRACT → 固定 DECLINE 文案。
        """
        if output.reply_type != ReplyType.ANSWER:
            return output
        business = cls.business_snapshots(snapshots)
        if not business or any(s.success for s in business):
            return output
        failure_types = {s.failure_type for s in business}
        if failure_types <= {FailureType.BUSINESS.value}:
            last = business[-1]
            message = (last.result or {}).get("message") or "抱歉，该请求暂时无法完成。"
            return output.model_copy(update={"content": message})
        return output.model_copy(
            update={
                "content": SERVICE_DECLINE_TEXT,
                "reply_type": ReplyType.DECLINE,
            }
        )
