"""编排入口（SPEC 1.2 时序）：消息落库 → Run → 执行 → 回写 → 应答。

会话口径：conversation_id = sender_id（与 V1 一致，SPEC 7.1）。
"""

import time

from app.conf.config import settings
from app.domain.enums import RunState
from app.domain.messages import BotMsg, MsgObject, ProcessResult
from app.errors import AgentExecutionError
from app.harness.context import compile_messages
from app.harness.executor import execute_run
from app.harness.run_service import complete_run, fail_run, start_run
from app.infra.db import SessionLocal
from app.memory.models import AgentRun
from app.memory.repository import load_history, save_message

EXECUTION_DECLINE = "系统繁忙，请稍后再试，您可以随时回来继续。"


async def process_chat(
    sender_id: str, msg_id: str, text: str | None, obj: MsgObject | None
) -> ProcessResult:
    t0 = time.perf_counter()
    obj_payload = obj.model_dump() if obj else None

    # 1) 历史快照 + 建 Run + 用户消息落库（先取历史，当前消息由 ContextCompiler 拼装）
    async with SessionLocal() as session:
        history = await load_history(session, sender_id, settings.history_message_limit)
        run = await start_run(
            session,
            conversation_id=sender_id,
            model_name=settings.llm_model,
            prompt_version=settings.prompt_version,
        )
        if obj_payload is not None:
            await save_message(
                session,
                conversation_id=sender_id,
                role="user",
                content_type="object",
                content=text,
                object_payload=obj_payload,
                run_id=run.id,
            )
        else:
            await save_message(
                session,
                conversation_id=sender_id,
                role="user",
                content=text,
                run_id=run.id,
            )
        await session.commit()

    # 2) 执行（不持有 DB 会话，LLM 调用期间不占连接）
    messages = compile_messages(history, text, obj_payload)
    try:
        outcome = await execute_run(run.id, messages)
    except AgentExecutionError as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        async with SessionLocal() as session:
            run_row = await session.get(AgentRun, run.id)
            await fail_run(
                session,
                run_row,
                error=exc.code,
                latency_ms=latency_ms,
            )
            await save_message(
                session,
                conversation_id=sender_id,
                role="bot",
                content=EXECUTION_DECLINE,
                run_id=run.id,
            )
            await session.commit()
        return ProcessResult(
            sender_id=sender_id, msg_id=msg_id, msgs=[BotMsg(text=EXECUTION_DECLINE)]
        )

    # 3) 回写 Run 结果 + bot 消息
    latency_ms = int((time.perf_counter() - t0) * 1000)
    async with SessionLocal() as session:
        run_row = await session.get(AgentRun, run.id)
        await complete_run(
            session,
            run_row,
            reply_type=outcome.output.reply_type.value,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            latency_ms=latency_ms,
            correction_attempts=outcome.correction_attempts,
        )
        await save_message(
            session,
            conversation_id=sender_id,
            role="bot",
            content=outcome.output.content,
            run_id=run.id,
        )
        await session.commit()

    return ProcessResult(
        sender_id=sender_id, msg_id=msg_id, msgs=[BotMsg(text=outcome.output.content)]
    )
