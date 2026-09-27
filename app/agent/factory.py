"""智能体组装（SPEC 6 章）：create_agent 骨架 + 动态提示词 + 技能收窄 + 调用上限。

与课程 factory.py 同构：system prompt 由 @dynamic_prompt 每次调用重渲染（不传静态 system_prompt）。
"""

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy

import app.skills.load_skill  # noqa: F401——load_skill 注册进 TOOL_CATALOG
import app.tools.business  # noqa: F401——业务工具注册进 TOOL_CATALOG
from app.agent.output import AgentOutput
from app.conf.config import settings
from app.harness.middleware.dynamic_prompt import support_prompt
from app.harness.middleware.skill_scope import SkillScopeMiddleware
from app.harness.runtime import AgentExecutionState, AgentRuntimeContext
from app.infra.llm import build_model
from app.tools.registry import TOOL_CATALOG


def create_support_agent():
    return create_agent(  # type: ignore[call-overload]
        model=build_model(),
        tools=TOOL_CATALOG.get_agent_tools(),
        response_format=ToolStrategy(AgentOutput),
        state_schema=AgentExecutionState,
        context_schema=AgentRuntimeContext,
        middleware=[
            support_prompt,
            SkillScopeMiddleware(),
            ToolCallLimitMiddleware(
                run_limit=settings.tool_call_limit, exit_behavior="error"
            ),
        ],
        name="智能客服小二",
    )


_agent = None


def get_agent():
    """harness 级单例：模型客户端、工具表与中间件只装配一次。"""
    global _agent
    if _agent is None:
        _agent = create_support_agent()
    return _agent
