"""AgentExecutor（SPEC 6.4）：ainvoke + 纠错循环骨架。

M1：输出 schema 由 response_format(ToolStrategy) 保证，纠错循环暂无校验器触发点；
M2 接入 AgentOutputValidator（事实检验 / 动作白名单）后，可纠正错误在此带反馈重跑。
"""

from dataclasses import dataclass

from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import BaseMessage

from app.agent.factory import get_agent
from app.agent.output import AgentOutput
from app.domain.enums import ReplyType, RunState
from app.errors import AgentExecutionError, TerminalErrorCode
from app.harness.tool_executor import current_run_id

TOOL_LIMIT_DECLINE = "这个问题有点复杂，我先记录下来转人工跟进，请您稍等。"


@dataclass
class RunOutcome:
    state: RunState
    output: AgentOutput | None = None
    error: str | None = None
    correction_attempts: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


def _tokens(cb: UsageMetadataCallbackHandler) -> tuple[int | None, int | None]:
    """回调的 usage_metadata 形态：{model_name: {input_tokens, output_tokens, ...}}，跨模型求和。"""
    um = getattr(cb, "usage_metadata", None) or {}
    if not um:
        return None, None
    if "input_tokens" in um:  # 平铺形态兜底
        return um.get("input_tokens"), um.get("output_tokens")
    in_toks = sum((v.get("input_tokens") or 0) for v in um.values() if isinstance(v, dict))
    out_toks = sum((v.get("output_tokens") or 0) for v in um.values() if isinstance(v, dict))
    return (in_toks or None), (out_toks or None)


async def execute_run(run_id: int, messages: list[BaseMessage]) -> RunOutcome:
    token = current_run_id.set(run_id)
    usage_cb = UsageMetadataCallbackHandler()
    in_toks, out_toks = _tokens(usage_cb)
    try:
        try:
            result = await get_agent().ainvoke(
                {"messages": messages}, config={"callbacks": [usage_cb]}
            )
        except ToolCallLimitExceededError:
            # 工具调用超限：固定 DECLINE 收尾，Run 正常完成（SPEC 6.3）
            return RunOutcome(
                state=RunState.COMPLETED,
                output=AgentOutput(reply_type=ReplyType.DECLINE, content=TOOL_LIMIT_DECLINE),
                correction_attempts=0,
                input_tokens=in_toks,
                output_tokens=out_toks,
            )
        attempts = 1
        output: AgentOutput = result["structured_response"]
        in_toks, out_toks = _tokens(usage_cb)
        return RunOutcome(
            state=RunState.COMPLETED,
            output=output,
            correction_attempts=attempts - 1,
            input_tokens=in_toks,
            output_tokens=out_toks,
        )
    except AgentExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001——执行层异常统一归终态错误码
        raise AgentExecutionError(
            TerminalErrorCode.AGENT_EXECUTION_FAILED, f"{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        current_run_id.reset(token)
