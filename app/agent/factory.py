"""智能体组装（SPEC 6 章）：create_agent 骨架 + 调用上限中间件。

技能收窄（skill_scope）与动态提示词（dynamic_prompt）中间件在 M2 随技能目录接入；
本模块保持组装点唯一，M1 只挂 ToolCallLimitMiddleware。
"""

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy

from app.agent.output import AgentOutput
from app.agent.prompts import BASE_PROMPT
from app.conf.config import settings
from app.infra.llm import build_model
from app.tools.registry import TOOL_CATALOG


def create_support_agent():
    return create_agent(  # type: ignore[call-overload]
        model=build_model(),
        tools=TOOL_CATALOG.get_agent_tools(),
        system_prompt=BASE_PROMPT,
        response_format=ToolStrategy(AgentOutput),
        middleware=[
            ToolCallLimitMiddleware(
                run_limit=settings.tool_call_limit, exit_behavior="error"
            )
        ],
        name="智能客服小二",
    )


_agent = None


def get_agent():
    """harness 级单例：模型客户端与工具表只装配一次。"""
    global _agent
    if _agent is None:
        _agent = create_support_agent()
    return _agent
