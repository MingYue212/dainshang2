"""结构化输出模型（SPEC 5.3）。

M2 设计精化（upgrade-log 第 11 节）：写操作确认走显式工具 request_refund_confirmation
（工具内硬校验订单已核实），不再依赖结构化字段表达确认意图——工具是模型更可靠的行动通道，
且与"提交也要过确认门"形成对称闭环。
"""

from typing import Literal

from pydantic import BaseModel

from app.domain.enums import ReplyType


class PageActionRequest(BaseModel):
    """模型只产出卡片编码 + 资源 ID；卡片内容由服务端拼装。"""

    card_code: Literal["ORDER_CARD", "PRODUCT_CARD"]
    resource_id: str


class AgentOutput(BaseModel):
    reply_type: ReplyType
    content: str
    page_action: PageActionRequest | None = None
