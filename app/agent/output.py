"""结构化输出模型（SPEC 5.3）：create_agent(response_format=ToolStrategy(AgentOutput))。"""

from typing import Literal

from pydantic import BaseModel

from app.domain.enums import ReplyType


class PageActionRequest(BaseModel):
    """模型只产出卡片编码 + 资源 ID；卡片内容由服务端拼装（M2 接入 ACTION_CATALOG）。"""

    card_code: Literal["ORDER_CARD", "PRODUCT_CARD"]
    resource_id: str


class AgentOutput(BaseModel):
    reply_type: ReplyType
    content: str
    page_action: PageActionRequest | None = None
