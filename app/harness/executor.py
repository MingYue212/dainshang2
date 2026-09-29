"""AgentExecutor（SPEC 6.4）：ainvoke + 纠错循环（≤2 次复用全轨迹）+ 确认态进入判定。

M2 实施精化（upgrade-log 第 11 节）：
- 确认请求走显式工具 request_refund_confirmation（工具内硬校验订单已核实）；
  executor 通过扫描本 Run 快照检测确认请求 → 置 AWAITING_CONFIRM；
- 百炼对"连续重复的工具调用"返回 400：捕获后转为一次纠错反馈重试，而非直接失败。

M3：on_delta 提供时挂 ContentStreamHandler，最终回答的 content 增量实时回调（WS 真流式）。
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import BaseMessage, SystemMessage

from app.agent.factory import get_agent
from app.agent.output import AgentOutput
from app.conf.config import settings
from app.domain.enums import ReplyType, RunState
from app.errors import (
    AgentExecutionError,
    AgentOutputValidationError,
    TerminalErrorCode,
)
from app.harness.runtime import AgentRuntimeContext
from app.harness.streaming import ContentStreamHandler
from app.harness.tool_executor import current_conversation_id, current_run_id
from app.infra.db import SessionLocal
from app.memory.repository import load_tool_snapshots
from app.rules.correction import OutputCorrectionRules
from app.validator.answer import AnswerValidator
from app.validator.output import AgentOutputValidator

TOOL_LIMIT_DECLINE = "这个问题有点复杂，我先记录下来转人工跟进，请您稍等。"
REPETITIVE_CALL_FEEDBACK = (
    "检测到连续重复的工具调用：请不要以相同参数重复调用同一工具。"
    "请基于已有工具结果继续——若需请求用户确认退款，调用 request_refund_confirmation "
    "后在回复中复述订单号与原因并询问是否确认；若信息已足够，直接给出最终回复。"
)
REQUEST_CONFIRMATION_TOOL = "request_refund_confirmation"


@dataclass
class RunOutcome:
    state: RunState
    output: AgentOutput | None = None
    error: str | None = None
    correction_attempts: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    pending_request: dict | None = None  # request_refund_confirmation 的登记结果


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


def _pending_request(snapshots) -> dict | None:
    """检测本 Run 是否登记了确认请求（request_refund_confirmation 成功调用）。"""
    hits = [
        s
        for s in snapshots
        if s.success and s.tool_name == REQUEST_CONFIRMATION_TOOL
    ]
    if not hits:
        return None
    args = hits[-1].arguments or {}
    return {
        "pending_action": "refund",
        "order_id": args.get("order_id"),
        "reason": args.get("reason"),
    }


async def _load_snapshots(run_id: int):
    async with SessionLocal() as session:
        return await load_tool_snapshots(session, run_id)


async def execute_run(
    run_id: int,
    conversation_id: str,
    messages: list[BaseMessage],
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> RunOutcome:
    run_token = current_run_id.set(run_id)
    conv_token = current_conversation_id.set(conversation_id)
    usage_cb = UsageMetadataCallbackHandler()
    callbacks: list = [usage_cb]
    if on_delta is not None:
        callbacks.append(ContentStreamHandler(on_delta))
    messages = list(messages)
    context = AgentRuntimeContext(
        run_id=run_id, conversation_id=conversation_id, user_id=conversation_id
    )
    attempts = 0
    try:
        while True:
            try:
                result = await get_agent().ainvoke(
                    {"messages": messages},
                    context=context,
                    config={"callbacks": callbacks},
                )
            except ToolCallLimitExceededError:
                in_toks, out_toks = _tokens(usage_cb)
                # 三级抢救：提交成功 > 已登记确认请求 > 普通降级——回复必须与事实一致
                try:
                    snapshots = await _load_snapshots(run_id)
                except Exception:  # noqa: BLE001
                    snapshots = ()
                submitted = next(
                    (
                        s
                        for s in snapshots
                        if s.success and s.tool_name == "submit_refund_application"
                    ),
                    None,
                )
                pending_request = _pending_request(snapshots)
                if submitted is not None:
                    request_id = (submitted.result or {}).get("request_id", "")
                    output = AgentOutput(
                        reply_type=ReplyType.ANSWER,
                        content=(
                            f"您的退款申请已提交成功，退款单号 {request_id}，"
                            "审核结果会通过站内消息通知您。"
                        ),
                    )
                    state = RunState.COMPLETED
                elif pending_request is not None:
                    output = AgentOutput(
                        reply_type=ReplyType.ANSWER,
                        content=(
                            f"已核实订单 {pending_request['order_id']}，退款原因："
                            f"{pending_request['reason']}。请回复“确认”提交退款申请。"
                        ),
                    )
                    state = RunState.AWAITING_CONFIRM
                else:
                    output = AgentOutput(
                        reply_type=ReplyType.DECLINE, content=TOOL_LIMIT_DECLINE
                    )
                    state = RunState.COMPLETED
                return RunOutcome(
                    state=state,
                    output=output,
                    correction_attempts=attempts,
                    input_tokens=in_toks,
                    output_tokens=out_toks,
                    pending_request=pending_request,
                )
            except Exception as exc:  # noqa: BLE001
                if "Repetitive tool calls" in str(exc) and attempts <= settings.max_correction_attempts:
                    # 百炼对重复工具调用的 400：转为纠错反馈重试
                    attempts += 1
                    messages = messages + [SystemMessage(content=REPETITIVE_CALL_FEEDBACK)]
                    continue
                raise
            attempts += 1
            output: AgentOutput = result["structured_response"]
            snapshots = await _load_snapshots(run_id)
            if output.reply_type == ReplyType.ANSWER:
                output = AnswerValidator.maybe_degrade(output, snapshots)
            in_toks, out_toks = _tokens(usage_cb)
            try:
                AgentOutputValidator.validate(output, snapshots)
            except AgentOutputValidationError as exc:
                if attempts > settings.max_correction_attempts:
                    return RunOutcome(
                        state=RunState.FAILED,
                        error=TerminalErrorCode.OUTPUT_VALIDATION_FAILED.value,
                        correction_attempts=attempts - 1,
                        input_tokens=in_toks,
                        output_tokens=out_toks,
                    )
                # 纠错重跑：复用完整消息轨迹（模型看得见自己上一轮的工具调用）
                messages = result["messages"] + [OutputCorrectionRules.build_feedback(exc)]
                continue

            pending_request = _pending_request(snapshots)
            if pending_request is not None:
                return RunOutcome(
                    state=RunState.AWAITING_CONFIRM,
                    output=output,
                    correction_attempts=attempts - 1,
                    input_tokens=in_toks,
                    output_tokens=out_toks,
                    pending_request=pending_request,
                )
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
        current_run_id.reset(run_token)
        current_conversation_id.reset(conv_token)
