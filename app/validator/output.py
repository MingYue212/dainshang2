"""校验编排（SPEC 12.1）：schema → 动作白名单 → 事实检验，顺序固定。"""

from dataclasses import dataclass

from app.agent.output import AgentOutput
from app.harness.snapshot import ToolCallSnapshot
from app.validator.action import PageActionValidator
from app.validator.answer import AnswerValidator


@dataclass
class ValidatedAgentOutput:
    output: AgentOutput
    snapshots: tuple[ToolCallSnapshot, ...]


class AgentOutputValidator:
    @classmethod
    def validate(
        cls,
        output: AgentOutput,
        snapshots: tuple[ToolCallSnapshot, ...],
    ) -> ValidatedAgentOutput:
        """任一环节不过即抛 AgentOutputValidationError（可纠正，进入纠错循环）。"""
        PageActionValidator.validate(output.page_action, snapshots)
        if output.reply_type.value == "ANSWER":
            successful = tuple(s for s in snapshots if s.success)
            AnswerValidator.validate_facts(output, successful)
        return ValidatedAgentOutput(output=output, snapshots=snapshots)
