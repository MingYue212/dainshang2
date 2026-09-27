"""上下文构建（SPEC 11 章）：三层历史裁剪 + 对象消息注入 + 待确认摘要注入。"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.conf.config import settings
from app.memory.models import ChatMessage

_OBJECT_LABEL = {"order": "订单卡片", "product": "商品卡片"}


def _content_text(msg: BaseMessage) -> str:
    return msg.content if isinstance(msg.content, str) else str(msg.content)


def trim_history(msgs: list[BaseMessage]) -> list[BaseMessage]:
    """三层裁剪：条数上限 → 字符预算（从新往旧保留）→ 丢弃首条 user 前的孤立 AI 消息。"""
    msgs = msgs[-settings.history_message_limit :]
    kept: list[BaseMessage] = []
    total = 0
    for m in reversed(msgs):
        cost = len(_content_text(m))
        if kept and total + cost > settings.history_character_budget:
            break
        kept.append(m)
        total += cost
    kept.reverse()
    for idx, m in enumerate(kept):
        if isinstance(m, HumanMessage):
            return kept[idx:]
    return []


def format_object(payload: dict) -> str:
    """对象消息 → 上下文占位文本（口径与 V1 history_builder 对齐）。"""
    label = _OBJECT_LABEL.get(payload.get("type", ""), "卡片")
    attrs = payload.get("attributes") or {}
    parts = [f"{label}: {payload.get('id', '')}"]
    if payload.get("title"):
        parts.append(f"标题「{payload['title']}」")
    for key in ("status", "amount", "price"):
        if attrs.get(key) is not None:
            parts.append(f"{key}={attrs[key]}")
    return "[用户点选了" + "，".join(parts) + "]"


def to_lc_message(row: ChatMessage) -> BaseMessage:
    text = row.content or ""
    if row.content_type == "object" and row.object_payload:
        text = (text + "\n" if text else "") + format_object(row.object_payload)
    if row.role == "user":
        return HumanMessage(content=text)
    return AIMessage(content=text)


def build_pending_confirmation_summary(pending_result: dict) -> str:
    """AWAITING_CONFIRM 摘要注入（SPEC 11.4）。"""
    order_id = pending_result.get("order_id", "")
    reason = pending_result.get("reason", "")
    return (
        f"[待确认操作] 用户此前申请为订单 {order_id} 提交退款（原因：{reason}），尚未获得确认。"
        "若用户本轮消息表示确认，请调用 submit_refund_application；"
        "若要修改，请按新信息重新核实并再次请求确认；"
        "若是无关话题，请正常回答新问题（该待确认将自动作废）。"
    )


def compile_messages(
    history: list[ChatMessage],
    user_text: str | None,
    obj_payload: dict | None,
    pending_summary: str | None = None,
) -> list[BaseMessage]:
    msgs = trim_history([to_lc_message(row) for row in history])
    current = user_text or ""
    if obj_payload:
        current = (current + "\n" if current else "") + format_object(obj_payload)
    if not current:
        current = "（用户发送了空消息）"
    if pending_summary:
        msgs.append(SystemMessage(content=pending_summary))
    msgs.append(HumanMessage(content=current))
    return msgs
