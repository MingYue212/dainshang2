"""交互模型：与 V1 atguigu.api.schemas 字段级兼容（SPEC 14.1，契约速查 A1）。"""

from typing import Any

from pydantic import BaseModel, Field


class ChatObjectPayload(BaseModel):
    type: str  # "order" | "product"
    id: str
    title: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    sender_id: str
    msg_id: str | None = None
    text: str | None = None
    object: ChatObjectPayload | None = None


class BotMsgResponse(BaseModel):
    text: str | None = None
    object: ChatObjectPayload | None = None


class ChatResponse(BaseModel):
    sender_id: str
    msg_id: str
    msgs: list[BotMsgResponse]


class HistoryMsgResponse(BaseModel):
    session_id: str
    role: str  # "user" | "bot"（V1 前端对未知 role 兜底为 bot）
    create_time: float
    text: str | None = None
    object: ChatObjectPayload | None = None


class ChatHistoryResponse(BaseModel):
    sender_id: str
    msgs: list[HistoryMsgResponse]
