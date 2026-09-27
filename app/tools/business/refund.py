"""退款工具组：request_refund_confirmation（请求确认）+ submit_refund_application（提交，含确认门）。

对话级二次确认闭环（SPEC 13 章，M2 精化为工具通道）：
1. 模型核实订单、问清原因后 → 调 request_refund_confirmation(order_id, reason)
   ——工具内硬校验"订单本轮已被 get_order 成功核实"，通过则登记待确认请求；
2. executor 读到待确认请求 → 本 Run 置 AWAITING_CONFIRM，下一轮注入摘要；
3. 用户确认 → 模型调 submit_refund_application → 确认门（pending 存在/订单一致/未超时）→ 放行调 18081；
   提交成功后待确认 Run 回写 COMPLETED；
4. 用户跑题 → 本 Run 结束时旧 pending 被 SUPERSEDED 清扫。
"""

from datetime import datetime

from pydantic import BaseModel, Field, TypeAdapter
from langchain_core.tools import tool
from sqlalchemy import select

from app.conf.config import settings
from app.domain.enums import RunState, ToolCategory
from app.harness.snapshot import ToolCallSnapshot
from app.harness.tool_executor import (
    current_conversation_id,
    current_run_id,
    execute_tool,
)
from app.infra.db import SessionLocal
from app.infra.commerce_client import CommerceError, get_commerce_client
from app.memory.models import AgentRun
from app.memory.repository import finalize_run, load_tool_snapshots
from app.tools.action import find_resource_snapshot
from app.tools.registry import TOOL_CATALOG, ToolDefinition

# 确认请求的登记结果结构（executor 通过扫描工具快照检测，无需独立状态通道）
_PENDING_ADAPTER = TypeAdapter(dict)

NO_PENDING_MESSAGE = (
    "尚未取得用户确认：请先核实订单并复述退款原因，"
    "调用 request_refund_confirmation 登记确认请求，待用户明确同意后再调用本工具。"
)


class SubmitRefundArgs(BaseModel):
    order_id: str = Field(pattern=r"^[ABC]\d{11}$", description="订单号，如 A20260408002")
    reason: str = Field(min_length=1, max_length=200, description="用户口述的退款原因原文")


class RequestConfirmationArgs(BaseModel):
    order_id: str = Field(pattern=r"^[ABC]\d{11}$", description="已核实的订单号")
    reason: str = Field(default="", max_length=200, description="用户口述的退款原因原文")


class OperationResultData(BaseModel):
    request_type: str
    request_id: str
    order_id: str
    status: str
    status_desc: str | None = None


REFUND_RESULT_ADAPTER = TypeAdapter(OperationResultData)


def check_pending(
    pending_result: dict | None,
    pending_created_at: datetime | None,
    order_id: str,
    now: datetime,
    timeout_minutes: int,
) -> str | None:
    """确认门纯函数：返回拒绝话术（BUSINESS 失败）或 None 表示放行。"""
    if not pending_result or pending_result.get("pending_action") != "refund":
        return NO_PENDING_MESSAGE
    if pending_result.get("order_id") != order_id:
        return "待确认的退款订单与本次提交不一致，请重新发起并再次向用户确认。"
    if pending_created_at is not None:
        age_minutes = (now - pending_created_at).total_seconds() / 60
        if age_minutes > timeout_minutes:
            return "待确认的退款请求已超时失效，请重新发起并再次向用户确认。"
    return None


async def _load_pending(session, conversation_id: str) -> AgentRun | None:
    rows = await session.execute(
        select(AgentRun)
        .where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.state == RunState.AWAITING_CONFIRM.value,
        )
        .order_by(AgentRun.id.desc())
        .limit(1)
    )
    return rows.scalars().first()


@tool("request_refund_confirmation", args_schema=RequestConfirmationArgs)
async def request_refund_confirmation(order_id: str, reason: str) -> str:
    """登记"请求用户确认退款"：核实订单后、提交退款前必须调用本工具。

    调用成功后请在回复中向用户复述订单号与退款原因，并明确询问是否确认提交；
    用户答复"确认"后才可调用 submit_refund_application。
    """
    run_id = current_run_id.get()
    conversation_id = current_conversation_id.get()

    async def runner() -> dict:
        if not run_id or not conversation_id:
            raise CommerceError("会话状态缺失，请重新发起退款申请")
        if not (reason or "").strip():
            # 参数宽容化：模型漏传原因时给可见反馈，而不是在解析层隐形失败
            raise CommerceError("尚未获得退款原因：请先向用户询问具体问题，再登记确认请求。")
        async with SessionLocal() as session:
            snapshots: tuple[ToolCallSnapshot, ...] = await load_tool_snapshots(session, run_id)
        # 硬校验：订单必须在本轮被 get_order 成功核实
        if find_resource_snapshot("ORDER_CARD", order_id, snapshots) is None:
            raise CommerceError(f"订单 {order_id} 尚未在本轮核实，请先调用 get_order")
        return {
            "pending_action": "refund",
            "order_id": order_id,
            "reason": reason,
            "message": "确认请求已登记：请在回复中复述订单号与退款原因，并询问用户是否确认提交。",
        }

    return await execute_tool(
        tool_name="request_refund_confirmation",
        arguments={"order_id": order_id, "reason": reason},
        runner=runner,
        schema=_PENDING_ADAPTER,
    )


_PENDING_ADAPTER = TypeAdapter(dict)


@tool("submit_refund_application", args_schema=SubmitRefundArgs)
async def submit_refund_application(order_id: str, reason: str) -> str:
    """为订单提交退款申请。仅在用户已明确同意后才可调用；调用即视为已确认。

    若返回"尚未取得用户确认"，请先调用 request_refund_confirmation 登记确认请求。
    """
    conversation_id = current_conversation_id.get()
    client = get_commerce_client()

    # 确认门（纯函数校验，便于单测）
    rejection: str | None = None
    pending: AgentRun | None = None
    if not conversation_id:
        rejection = NO_PENDING_MESSAGE
    else:
        async with SessionLocal() as session:
            pending = await _load_pending(session, conversation_id)
        rejection = check_pending(
            pending.result if pending else None,
            pending.created_at if pending else None,
            order_id,
            datetime.now(),
            settings.pending_confirm_timeout_minutes,
        )
    if rejection is not None:
        return await execute_tool(
            tool_name="submit_refund_application",
            arguments={"order_id": order_id, "reason": reason},
            runner=lambda: _reject(rejection),
            schema=REFUND_RESULT_ADAPTER,
        )

    # 放行：调用业务 API，成功后回写待确认 Run 为 COMPLETED
    submit_result: dict | None = None

    async def runner() -> dict:
        nonlocal submit_result
        data = await client.post_data(
            f"/orders/{order_id}/refund-applications",
            {"submitted_by": "ai-agent", "reason": reason},
        )
        submit_result = data
        return data

    envelope = await execute_tool(
        tool_name="submit_refund_application",
        arguments={"order_id": order_id, "reason": reason},
        runner=runner,
        schema=REFUND_RESULT_ADAPTER,
        ok_message=(
            "退款申请已提交成功：请立即向用户转达提交结果与退款单号，"
            "然后结束本轮回复，不要再调用任何工具。"
        ),
    )

    if submit_result is not None and pending is not None:
        try:
            async with SessionLocal() as session:
                row = await session.get(AgentRun, pending.id)
                if row is not None and row.state == RunState.AWAITING_CONFIRM.value:
                    await finalize_run(
                        session,
                        row,
                        state=RunState.COMPLETED,
                        reply_type="ANSWER",
                        result={
                            **(row.result or {}),
                            "refund_request_id": submit_result.get("request_id"),
                        },
                    )
                    await session.commit()
        except Exception:  # noqa: BLE001——回写失败不影响已成功的退款
            pass
    return envelope


async def _reject(message: str) -> dict:
    raise CommerceError(message)


TOOL_CATALOG.register(
    ToolDefinition(tool=request_refund_confirmation, category=ToolCategory.GUIDANCE)
)
TOOL_CATALOG.register(
    ToolDefinition(tool=submit_refund_application, category=ToolCategory.BUSINESS)
)
