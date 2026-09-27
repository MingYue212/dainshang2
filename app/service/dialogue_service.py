"""编排入口（SPEC 1.2 时序）：消息落库 → Run → 执行（纠错/确认门）→ 回写 → 应答。

M2 新增：待确认摘要注入、confirmation → AWAITING_CONFIRM、页面动作卡片下发、
SUPERSEDED 清扫、校验耗尽降级。
"""

import time

from app.conf.config import settings
from app.domain.enums import RunState
from app.domain.messages import BotMsg, MsgObject, ProcessResult
from app.errors import AgentExecutionError, TerminalErrorCode
from app.harness.context import build_pending_confirmation_summary, compile_messages
from app.harness.executor import execute_run
from app.harness.run_service import (
    await_confirmation,
    complete_run,
    fail_run,
    load_latest_pending,
    start_run,
    supersede_stale_pendings,
)
from app.infra.db import SessionLocal
from app.memory.models import AgentRun
from app.memory.repository import load_history, load_tool_snapshots, save_message
from app.tools.action import build_card

EXECUTION_DECLINE = "系统繁忙，请稍后再试，您可以随时回来继续。"
VALIDATION_DECLINE = "抱歉，这个问题我暂时无法给出可靠答复，已为您转人工跟进。"


async def process_chat(
    sender_id: str, msg_id: str, text: str | None, obj: MsgObject | None
) -> ProcessResult:
    t0 = time.perf_counter()
    obj_payload = obj.model_dump() if obj else None

    # 1) 历史快照 + 待确认 Run + 建 Run + 用户消息落库
    async with SessionLocal() as session:
        history = await load_history(session, sender_id, settings.history_message_limit)
        pending = await load_latest_pending(session, sender_id)
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

    # 2) 执行（不持有 DB 会话）
    pending_summary = (
        build_pending_confirmation_summary(pending.result)
        if pending is not None and pending.result
        else None
    )
    messages = compile_messages(history, text, obj_payload, pending_summary)
    try:
        outcome = await execute_run(run.id, sender_id, messages)
    except AgentExecutionError as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        async with SessionLocal() as session:
            run_row = await session.get(AgentRun, run.id)
            await fail_run(session, run_row, error=exc.code, latency_ms=latency_ms)
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

    # 3) 回写 Run 终态 + bot 消息（含动作卡片）+ SUPERSEDED 清扫
    latency_ms = int((time.perf_counter() - t0) * 1000)
    assert outcome.output is not None
    reply_type = outcome.output.reply_type.value
    bot_msgs: list[BotMsg] = [BotMsg(text=outcome.output.content)]

    async with SessionLocal() as session:
        run_row = await session.get(AgentRun, run.id)
        if outcome.state == RunState.AWAITING_CONFIRM:
            await await_confirmation(
                session,
                run_row,
                reply_type=reply_type,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                latency_ms=latency_ms,
                correction_attempts=outcome.correction_attempts,
                result=outcome.pending_request,
            )
        elif outcome.state == RunState.FAILED:
            await fail_run(
                session,
                run_row,
                error=TerminalErrorCode(outcome.error),
                latency_ms=latency_ms,
                correction_attempts=outcome.correction_attempts,
            )
        else:
            await complete_run(
                session,
                run_row,
                reply_type=reply_type,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                latency_ms=latency_ms,
                correction_attempts=outcome.correction_attempts,
            )

        # 页面动作：服务端拼装卡片（校验已保证资源核实过）
        if outcome.output.page_action is not None:
            try:
                snapshots = await load_tool_snapshots(session, run.id)
                card = build_card(
                    outcome.output.page_action.card_code,
                    outcome.output.page_action.resource_id,
                    snapshots,
                )
                await save_message(
                    session,
                    conversation_id=sender_id,
                    role="bot",
                    content_type="object",
                    object_payload=card,
                    run_id=run.id,
                )
                bot_msgs.append(BotMsg(object=card))
            except Exception:  # noqa: BLE001——卡片拼装失败不影响文本回复
                pass

        # 清扫未被消费的旧待确认 Run（新 pending 自身被 exclude 保留）
        await supersede_stale_pendings(session, sender_id, exclude_run_id=run.id)
        await session.commit()

    return ProcessResult(sender_id=sender_id, msg_id=msg_id, msgs=bot_msgs)
