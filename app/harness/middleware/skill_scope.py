"""技能工具收窄中间件（SPEC 6.2，课程 skills/middleware.py 同构）：

未激活技能 → 只暴露 load_skill；激活后 → {load_skill} ∪ skill.tools，
并强制 parallel_tool_calls=False（qwen 已实测支持，见 scripts/probe_qwen.py）。
"""

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)

from app.agent.output import AgentOutput
from app.harness.runtime import AgentExecutionState, AgentRuntimeContext
from app.domain.enums import SkillCode
from app.skills.catalog import get_skill


class SkillScopeMiddleware(
    AgentMiddleware[AgentExecutionState, AgentRuntimeContext, AgentOutput]
):
    """根据当前 Skill 限制模型可见的工具。"""

    async def awrap_model_call(
        self,
        request: ModelRequest[AgentRuntimeContext],
        handler: Callable[
            [ModelRequest[AgentRuntimeContext]],
            Awaitable[ModelResponse[AgentOutput]],
        ],
    ) -> ModelResponse[AgentOutput]:
        active = request.state.get("active_skill_code")
        if isinstance(active, str):
            active = SkillCode(active)

        if active is None:
            allowed_tool_names = {"load_skill"}
        else:
            allowed_tool_names = {"load_skill", *get_skill(active).tools}

        scoped_request = request.override(
            tools=[tool for tool in request.tools if tool.name in allowed_tool_names],
            model_settings={
                **request.model_settings,
                "parallel_tool_calls": False,
            },
        )
        return await handler(scoped_request)
