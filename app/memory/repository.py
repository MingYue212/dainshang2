"""三张表的读写仓储（调用方负责 commit）。"""

from sqlalchemy import select

from app.domain.enums import RunState, transition_allowed
from app.memory.models import AgentRun, AgentToolCall, ChatMessage


async def save_message(
    session,
    *,
    conversation_id: str,
    role: str,
    content_type: str = "text",
    content: str | None = None,
    object_payload: dict | None = None,
    run_id: int | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        conversation_id=conversation_id,
        role=role,
        content_type=content_type,
        content=content,
        object_payload=object_payload,
        run_id=run_id,
    )
    session.add(msg)
    await session.flush()
    return msg


async def load_history(
    session, conversation_id: str, limit: int = 200
) -> list[ChatMessage]:
    rows = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(limit)
    )
    return list(rows.scalars())


async def create_run(session, *, conversation_id: str, model_name: str, prompt_version: str) -> AgentRun:
    run = AgentRun(
        conversation_id=conversation_id,
        state=RunState.RUNNING.value,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    session.add(run)
    await session.flush()
    return run


async def finalize_run(
    session,
    run: AgentRun,
    *,
    state: RunState,
    reply_type: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    correction_attempts: int = 0,
    result: dict | None = None,
) -> AgentRun:
    if not transition_allowed(RunState(run.state), state):
        raise ValueError(f"非法状态流转: {run.state} -> {state}")
    run.state = state.value
    run.reply_type = reply_type
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.latency_ms = latency_ms
    run.error = error
    run.correction_attempts = correction_attempts
    run.result = result
    await session.flush()
    return run


async def record_tool_call_start(
    session, *, run_id: int, tool_call_id: str, tool_name: str, arguments: dict
) -> int:
    row = AgentToolCall(
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        success=False,
    )
    session.add(row)
    await session.flush()
    return row.id


async def record_tool_call_end(
    session,
    row_id: int,
    *,
    result: dict | None,
    success: bool,
    failure_type: str | None,
    latency_ms: int | None,
) -> None:
    row = await session.get(AgentToolCall, row_id)
    if row is None:  # 理论不可达（同会话内先 start 后 end）
        return
    row.result = result
    row.success = success
    row.failure_type = failure_type
    row.latency_ms = latency_ms
    await session.flush()


async def load_tool_snapshots(session, run_id: int):
    """按 run_id 读取全部工具调用快照（含失败）——事实检验与动作白名单的证据源。"""
    from sqlalchemy import select

    from app.harness.snapshot import ToolCallSnapshot

    rows = await session.execute(
        select(AgentToolCall)
        .where(AgentToolCall.run_id == run_id)
        .order_by(AgentToolCall.id.asc())
    )
    return tuple(
        ToolCallSnapshot(
            tool_call_id=row.tool_call_id,
            tool_name=row.tool_name,
            arguments=row.arguments or {},
            result=row.result,
            success=bool(row.success),
            failure_type=row.failure_type,
        )
        for row in rows.scalars()
    )


async def save_message_tool_call(
    session,
    *,
    run_id: int,
    tool_call_id: str,
    tool_name: str,
    arguments: dict,
    result: dict | None,
) -> None:
    """不经信封执行器的轻量快照（如 load_skill 这类控制类工具）。"""
    row = AgentToolCall(
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        success=True,
    )
    session.add(row)
    await session.flush()
