"""领域消息模型：与 V1 atguigu.domain.message 同构，保证交互层字段级兼容。"""

import time
from enum import Enum

from pydantic import BaseModel, Field


class MsgType(str, Enum):
    TEXT = "text"
    OBJECT = "object"


class MsgObject(BaseModel):
    type: str  # "order" | "product"
    id: str
    title: str | None = None
    attributes: dict = Field(default_factory=dict)


class UserMsg(BaseModel):
    msg_id: str
    sender_id: str
    type: MsgType = MsgType.TEXT
    text: str | None = None
    object: MsgObject | None = None
    create_time: float = Field(default_factory=time.time)


class BotMsg(BaseModel):
    text: str | None = None
    object: MsgObject | None = None
    create_time: float = Field(default_factory=time.time)


class ProcessResult(BaseModel):
    sender_id: str
    msg_id: str
    msgs: list[BotMsg] = Field(default_factory=list)
