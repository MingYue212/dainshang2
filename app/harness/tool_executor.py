"""工具执行器（SPEC 6.5）：执行前取证、执行后回填、异常归档为信封——永不向模型抛异常。"""

import logging
import time
import uuid
from contextvars import ContextVar

import httpx
from pydantic import TypeAdapter, ValidationError

from app.domain.enums import FailureType
from app.infra.commerce_client import CommerceError
from app.infra.db import SessionLocal
from app.memory.repository import record_tool_call_end, record_tool_call_start
from app.tools.envelope import OK_CODE, TOOL_FAILED_CODE, ToolResult

logger = logging.getLogger(__name__)

# executor 在 ainvoke 前设置，工具薄壳内读取——工具无需感知会话 plumbing
current_run_id: ContextVar[int | None] = ContextVar("current_run_id", default=None)
current_conversation_id: ContextVar[str | None] = ContextVar(
    "current_conversation_id", default=None
)

GENERIC_SERVICE_MESSAGE = "订单服务暂时不可用，请稍后再试"


def classify_failure(exc: Exception) -> tuple[FailureType, str]:
    """异常 → (失败类型, 面向用户的可读消息)。纯函数，单测锁定。"""
    if isinstance(exc, CommerceError):
        return FailureType.BUSINESS, exc.message
    if isinstance(exc, ValidationError):
        return FailureType.CONTRACT, "服务返回数据不符合约定结构，请稍后再试"
    if isinstance(exc, httpx.HTTPError):
        return FailureType.SERVICE_CALL, GENERIC_SERVICE_MESSAGE
    return FailureType.SERVICE_CALL, "服务内部异常，请稍后再试"


async def execute_tool(
    *,
    tool_name: str,
    arguments: dict,
    runner,
    schema: TypeAdapter,
    ok_message: str = "ok",
) -> str:
    """执行一个业务工具调用并返回信封 JSON 字符串。

    runner: 零参协程工厂（业务取数）；schema: TypeAdapter（data 结构校验）；
    ok_message: 成功信封的话术（可携带对模型的后续行为指引）。
    """
    run_id = current_run_id.get()
    tool_call_id = uuid.uuid4().hex

    row_id: int | None = None
    try:
        async with SessionLocal() as session:
            row_id = await record_tool_call_start(
                session,
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
            )
            await session.commit()
    except Exception:
        # 快照失败不阻断业务调用（但事实检验将失去证据源，需告警）
        logger.exception("工具调用快照落库失败: %s", tool_name)

    t0 = time.perf_counter()
    success = False
    failure_type: FailureType | None = None
    message = ""
    data = None
    try:
        raw = await runner()
        validated = schema.validate_python(raw)
        data = schema.dump_python(validated, mode="json")
        success = True
        message = ok_message
    except Exception as exc:  # noqa: BLE001——信封化是本模块职责
        failure_type, message = classify_failure(exc)

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if row_id is not None:
        try:
            async with SessionLocal() as session:
                await record_tool_call_end(
                    session,
                    row_id,
                    # 成功存业务数据（事实检验的证据源），失败存失败话术
                    result=data if success else {"message": message},
                    success=success,
                    failure_type=failure_type.value if failure_type else None,
                    latency_ms=latency_ms,
                )
                await session.commit()
        except Exception:
            logger.exception("工具调用快照回填失败: %s", tool_name)

    if success:
        result = ToolResult[object](
            success=True, code=OK_CODE, message=message, data=data
        )
    else:
        result = ToolResult[object](
            success=False,
            code=TOOL_FAILED_CODE,
            failure_type=failure_type.value if failure_type else None,
            message=message,
            data=None,
        )
    return result.model_dump_json()
