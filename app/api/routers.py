"""对外契约端点（SPEC 14 章）：/api/chat、/api/chat/history、/api/digital-human/credentials。

WS /ws/chat 在 M3 随真流式接入（bot_message_delta 事件）。
"""

import uuid

from fastapi import APIRouter

from app.api.schemas import (
    BotMsgResponse,
    ChatHistoryResponse,
    ChatObjectPayload,
    ChatRequest,
    ChatResponse,
    HistoryMsgResponse,
)
from app.conf.config import settings
from app.domain.messages import MsgObject, ProcessResult
from app.infra.db import SessionLocal
from app.memory.repository import load_history
from app.service.dialogue_service import process_chat

router = APIRouter()


def to_chat_response(result: ProcessResult) -> ChatResponse:
    """领域结果 → 交互契约（纯转换，单测锁定字段级兼容）。"""
    msgs = [
        BotMsgResponse(
            text=m.text,
            object=(
                ChatObjectPayload(**m.object.model_dump()) if m.object else None
            ),
        )
        for m in result.msgs
    ]
    return ChatResponse(sender_id=result.sender_id, msg_id=result.msg_id, msgs=msgs)


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    msg_id = req.msg_id or str(uuid.uuid4())
    obj = MsgObject(**req.object.model_dump()) if req.object else None
    result = await process_chat(req.sender_id, msg_id, req.text, obj)
    return to_chat_response(result)


@router.get("/api/chat/history", response_model=ChatHistoryResponse)
async def history(sender_id: str) -> ChatHistoryResponse:
    async with SessionLocal() as session:
        rows = await load_history(session, sender_id, limit=200)
    msgs = [
        HistoryMsgResponse(
            session_id=sender_id,
            role=row.role,
            create_time=row.created_at.timestamp(),
            text=row.content,
            object=(
                ChatObjectPayload(**row.object_payload) if row.object_payload else None
            ),
        )
        for row in rows
    ]
    return ChatHistoryResponse(sender_id=sender_id, msgs=msgs)


@router.get("/api/digital-human/credentials")
async def digital_human_credentials() -> dict:
    return {
        "app_id": settings.digital_human_app_id,
        "app_secret": settings.digital_human_app_secret,
        "gateway_server": settings.digital_human_gateway_server,
    }
