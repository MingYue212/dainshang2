"""Run 生命周期服务：创建 / 完成 / 失败，唯一的状态机流转入口。"""

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
    error: TerminalErrorCode,
    latency_ms: int | None,
    correction_attempts: int = 0,
) -> AgentRun:
    return await finalize_run(
        session,
        run,
        state=RunState.FAILED,
        error=error.value,
        latency_ms=latency_ms,
        correction_attempts=correction_attempts,
    )
