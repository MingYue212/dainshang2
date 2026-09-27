from typing import Any

from pydantic import BaseModel


class ChatObjPayload(BaseModel):
    """对话对象"""

    type: str # 要知道是商品还是订单
    obj_id: str # 哪个商品或者订单
    title: str | None = None
    description: dict[str, Any] = {}


class ChatRequest(BaseModel):
    """对话请求"""

    sender_id: str # 谁发送的消息
    msg_id: str | None = None
    text: str | None = None
    obj: ChatObjPayload | None = None


class BotMsg(BaseModel):
    """机器人消息"""

    text: str | None = None
    obj: ChatObjPayload | None = None


class ChatResponse(BaseModel):
    """对话响应"""

    sender_id: str # 响应给谁
    msg_id: str # 消息id
    msgs: list[BotMsg]


class HistoryMsgResponse(BaseModel):
    """对话历史消息响应"""

    role: str # 是用户还是机器人
    text: str | None = None
    obj: ChatObjPayload | None = None


class ChatHistoryResponse(BaseModel):
    """对话历史响应"""

    sender_id: str # 响应给谁
    msgs: list[HistoryMsgResponse]
