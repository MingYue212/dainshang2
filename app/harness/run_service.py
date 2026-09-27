"""Run 生命周期服务：创建 / 完成 / 失败 / 待确认 / 作废清扫，唯一的状态机流转入口。"""

from sqlalchemy import select

from app.domain.enums import RunState
from app.errors import TerminalErrorCode
from app.memory.models import AgentRun
from app.memory.repository import create_run, finalize_run


async def start_run(session, *, conversation_id: str, model_name: str, prompt_version: str) -> AgentRun:
    return await create_run(
        session,
        conversation_id=conversation_id,
        model_name=model_name,
        prompt_version=prompt_version,
    )


async def complete_run(
    session,
    run: AgentRun,
    *,
    reply_type: str,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
    correction_attempts: int,
    result: dict | None = None,
) -> AgentRun:
    return await finalize_run(
        session,
        run,
        state=RunState.COMPLETED,
        reply_type=reply_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        correction_attempts=correction_attempts,
        result=result,
    )


async def fail_run(
    session,
    run: AgentRun,
    *,
    error: TerminalErrorCode | str,
    latency_ms: int | None,
    correction_attempts: int = 0,
) -> AgentRun:
    error_code = error.value if isinstance(error, TerminalErrorCode) else str(error)
    return await finalize_run(
        session,
        run,
        state=RunState.FAILED,
        error=error_code,
        latency_ms=latency_ms,
        correction_attempts=correction_attempts,
    )


async def await_confirmation(
    session,
    run: AgentRun,
    *,
    reply_type: str,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
    correction_attempts: int,
    result: dict,
) -> AgentRun:
    """进入 AWAITING_CONFIRM（confirmation 字段已通过硬校验后调用）。"""
    return await finalize_run(
        session,
        run,
        state=RunState.AWAITING_CONFIRM,
        reply_type=reply_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        correction_attempts=correction_attempts,
        result=result,
    )


async def load_latest_pending(session, conversation_id: str) -> AgentRun | None:
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


async def supersede_stale_pendings(
    session, conversation_id: str, exclude_run_id: int
) -> int:
    """本轮结束后清扫未被消费的旧待确认 Run（RUNNING→AWAITING_CONFIRM→SUPERSEDED）。

    消费（确认提交成功）的 pending 已由退款工具回写 COMPLETED，不会被扫到。
    """
    rows = await session.execute(
        select(AgentRun).where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.state == RunState.AWAITING_CONFIRM.value,
            AgentRun.id != exclude_run_id,
        )
    )
    count = 0
    for run in rows.scalars():
        await finalize_run(session, run, state=RunState.SUPERSEDED)
        count += 1
    return count
