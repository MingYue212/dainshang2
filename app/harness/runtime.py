"""Agent 运行时状态与上下文（课程 run/runtime.py 同构）。"""

from dataclasses import dataclass
from typing_extensions import NotRequired

from langchain.agents import AgentState

from app.agent.output import AgentOutput
from app.domain.enums import SkillCode


@dataclass(frozen=True)
class AgentRuntimeContext:
    """提供给 Agent 的单次运行信息（user_id 演示口径 = conversation_id，SPEC 8 章）。"""

    run_id: int
    conversation_id: str
    user_id: str


class AgentExecutionState(AgentState[AgentOutput]):  # type: ignore[misc]
    """Agent 多步骤执行期间可变的状态：当前激活的技能。"""

    active_skill_code: NotRequired[SkillCode]
