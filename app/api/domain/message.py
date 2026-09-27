


from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any




class MsgType(str, Enum):
    """消息类型枚举：纯文本(text)或业务对象(object)。"""
    TEXT = "text"
    OBJECT = "object"
    


@dataclass(slots=True)
class MsgObject:
    """消息体对象：可附带在消息中的业务实体(如图片/商品)。"""
    type:str
    id:str
    title:str | None = None
    attributes:dict[str,Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data:dict[str,Any]) -> 'MsgObject':
        return cls(
            type=data.get("type"),
            id=data.get("id"),
            title=data.get("title"),
            attributes=data.get("attributes") or {}
            )

@dataclass(slots=True)
class UserMsg:
    """用户消息：包含发送者、类型及文本/对象内容。"""
    msg_id:str
    sender_id:str
    type:MsgType
    text:str | None = None
    object:MsgObject | None = None
    create_time:float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data:dict[str,Any]) -> 'UserMsg':
        return cls(
            msg_id=data.get("msg_id"),
            sender_id=data.get("sender_id"),
            type=MsgType(data.get("type")),
            text=data.get("text"),
            object=MsgObject.from_dict(data.get("object")) if data.get("object") else None,
            create_time=data.get("create_time") or time.time()
        )




@dataclass(slots=True)
class BotMsg:
    """机器人回复消息：可含文本和/或业务对象。"""
    text:str | None = None
    object:MsgObject | None = None
    create_time:float = field(default_factory=time.time)
    

@dataclass(slots=True)
class ProcessResult:
    """处理结果：本轮对话机器人要返回给用户的消息集合。"""
    sender_id:str
    msg_id:str
    msgs:list[BotMsg] = field(default_factory=list)




