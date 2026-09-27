"""qwen 三项实测（SPEC 18 章 M1 交付物）：

1. bind_tools 基础工具调用
2. bind_tools(parallel_tool_calls=False) 参数支持
3. create_agent + ToolStrategy 结构化输出（response_format）

用法：uv run python scripts/probe_qwen.py
"""

import asyncio
import json

from pydantic import BaseModel

from app.infra.llm import build_model

PROBE_ORDER_ID = "A20260408002"


async def probe_bind_tools() -> dict:
    from langchain_core.tools import tool

    @tool
    def get_order_probe(order_id: str) -> str:
        """查询订单详情：状态、金额、收货信息与商品明细。"""

        return "ok"

    try:
        model = build_model()
        resp = await model.bind_tools([get_order_probe]).ainvoke(
            f"帮我查一下订单 {PROBE_ORDER_ID} 的状态"
        )
        calls = getattr(resp, "tool_calls", None) or []
        return {"ok": bool(calls), "tool_calls": [c.get("name") for c in calls]}
    except Exception as exc:  # noqa: BLE001——探针需捕获一切
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


async def probe_parallel_tool_calls_false() -> dict:
    from langchain_core.tools import tool

    @tool
    def get_order_probe2(order_id: str) -> str:
        """查询订单详情。"""

        return "ok"

    try:
        model = build_model()
        resp = await model.bind_tools(
            [get_order_probe2], parallel_tool_calls=False
        ).ainvoke(f"查订单 {PROBE_ORDER_ID}")
        calls = getattr(resp, "tool_calls", None) or []
        return {
            "ok": True,
            "parallel_accepted": True,
            "tool_calls": [c.get("name") for c in calls],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "parallel_accepted": False,
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }


async def probe_tool_strategy() -> dict:
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.tools import tool

    class AgentOutputProbe(BaseModel):
        reply_type: str
        content: str

    @tool
    def get_order_probe3(order_id: str) -> str:
        """查询订单详情。"""

        return "ok"

    # 结论：thinking 模式不支持 tool_choice=required；extra_body 只在构造器级生效
    from langchain_openai import ChatOpenAI
    from app.conf.config import settings as _s
    model = ChatOpenAI(
        model=_s.llm_model, base_url=_s.llm_base_url, api_key=_s.llm_api_key,
        temperature=0, use_responses_api=False,
        extra_body={"enable_thinking": False},
    )
    try:
        agent = create_agent(
            model=model,
            tools=[get_order_probe3],
            response_format=ToolStrategy(AgentOutputProbe),
            name="probe",
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": f"请查询订单 {PROBE_ORDER_ID} 并用一句话告诉我状态"}]}
        )
        sr = result.get("structured_response")
        return {
            "ok": sr is not None,
            "fix": "extra_body={'enable_thinking': False}",
            "parsed": sr.model_dump() if sr else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "fix": "extra_body={'enable_thinking': False}",
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }


async def probe_provider_strategy() -> dict:
    """对照组：ProviderStrategy（json_schema response_format）在 thinking 默认开启下是否可用。"""
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ProviderStrategy
    from langchain_core.tools import tool

    class AgentOutputProbe2(BaseModel):
        reply_type: str
        content: str

    @tool
    def get_order_probe4(order_id: str) -> str:
        """查询订单详情。"""

        return "ok"

    try:
        agent = create_agent(
            model=build_model(),
            tools=[get_order_probe4],
            response_format=ProviderStrategy(AgentOutputProbe2),
            name="probe2",
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": f"请查询订单 {PROBE_ORDER_ID} 并用一句话告诉我状态"}]}
        )
        sr = result.get("structured_response")
        return {"ok": sr is not None, "parsed": sr.model_dump() if sr else None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


async def main() -> None:
    report = {
        "bind_tools": await probe_bind_tools(),
        "parallel_tool_calls_false": await probe_parallel_tool_calls_false(),
        "tool_strategy_no_thinking": await probe_tool_strategy(),
        "provider_strategy": await probe_provider_strategy(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
