"""对外契约端点（SPEC 14 章）：/api/chat、/ws/chat、/api/chat/history、/api/digital-human/credentials。

M3：WS 保留 V1 全部事件语义（status/bot_message/error），新增 bot_message_delta
token 级分片事件——逐段出字的判定载体是根目录 ws-test.html（V1 前端不消费 WS，零改动不受影响）。
"""

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


# ---- WS /ws/chat（M3 真流式） --------------------------------------------------


class _WsSession:
    """单条 WS 消息的发送辅助：统一事件帧结构（字段与 V1 契约一致）。"""

    def __init__(self, websocket: WebSocket, sender_id: str, msg_id: str) -> None:
        self._ws = websocket
        self.sender_id = sender_id
        self.msg_id = msg_id

    async def status(self, value: str) -> None:
        await self._ws.send_json(
            {"type": "status", "sender_id": self.sender_id, "data": {"status": value}}
        )

    async def delta(self, text: str) -> None:
        await self._ws.send_json(
            {
                "type": "bot_message_delta",
                "sender_id": self.sender_id,
                "msg_id": self.msg_id,
                "data": {"delta": text},
            }
        )

    async def bot_message(self, text: str | None, object_payload: dict | None = None) -> None:
        await self._ws.send_json(
            {
                "type": "bot_message",
                "sender_id": self.sender_id,
                "msg_id": self.msg_id,
                "data": {"text": text, "object": object_payload},
            }
        )

    async def error(self, code: str, message: str) -> None:
        await self._ws.send_json(
            {
                "type": "error",
                "sender_id": self.sender_id,
                "data": {"code": code, "message": message},
            }
        )


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "data": {"code": "INVALID_JSON", "message": "消息不是合法 JSON"}}
                )
                continue

            if payload.get("type") == "cancel":
                # 与 V1 语义一致：仅回执，不中断生成
                sender_id = str(payload.get("sender_id", ""))
                await websocket.send_json(
                    {"type": "status", "sender_id": sender_id, "data": {"status": "cancelled"}}
                )
                continue
            if payload.get("type") != "message":
                continue

            sender_id = str(payload.get("sender_id", ""))
            msg_id = str(payload.get("message_id") or uuid.uuid4())
            text = payload.get("text")
            obj_payload = payload.get("object")
            obj = MsgObject(**obj_payload) if obj_payload else None
            session = _WsSession(websocket, sender_id, msg_id)

            await session.status("thinking")
            try:
                result = await process_chat(
                    sender_id, msg_id, text, obj, on_delta=session.delta
                )
                for m in result.msgs:
                    await session.bot_message(
                        m.text, m.object.model_dump() if m.object else None
                    )
                await session.status("done")
            except Exception:  # noqa: BLE001——单条消息失败不断开连接
                logging.getLogger(__name__).exception("WS 消息处理异常 sender=%s", sender_id)
                await session.error("PROCESS_ERROR", "处理该消息时出现异常，请稍后重试")
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001——连接级异常
        try:
            await websocket.send_json(
                {"type": "error", "data": {"code": "INTERNAL_ERROR", "message": "连接异常"}}
            )
        except Exception:  # noqa: BLE001
            pass
