"""页面动作白名单（SPEC 9.2）：模型只报 card_code + resource_id，卡片由服务端组装。

前端已支持渲染 bot 消息中的 order/product 卡片（契约速查 C1），字段口径与
ServiceChat.vue / ChatMessage.vue 的取值逻辑对齐。
"""

from dataclasses import dataclass

from app.errors import AgentOutputValidationError, CorrectableErrorCode
from app.harness.snapshot import ToolCallSnapshot


@dataclass(frozen=True)
class ActionDefinition:
    card_code: str
    label: str
    tool_name: str      # 资源核实所需工具
    id_argument: str    # 该工具 arguments 中资源 ID 的键名


ACTION_CATALOG: dict[str, ActionDefinition] = {
    "ORDER_CARD": ActionDefinition(
        card_code="ORDER_CARD", label="订单卡片", tool_name="get_order", id_argument="order_id"
    ),
    "PRODUCT_CARD": ActionDefinition(
        card_code="PRODUCT_CARD", label="商品卡片", tool_name="get_product", id_argument="product_id"
    ),
}


def render_action_index() -> str:
    return "\n".join(
        f"- {d.card_code}({d.id_argument}): {d.label}，仅可引用本轮已成功查询的资源"
        for d in ACTION_CATALOG.values()
    )


def find_resource_snapshot(
    card_code: str, resource_id: str, snapshots: tuple[ToolCallSnapshot, ...]
) -> ToolCallSnapshot | None:
    """资源核实：该资源必须在本 Run 被对应工具成功查询过。"""
    definition = ACTION_CATALOG.get(card_code)
    if definition is None:
        return None
    for s in snapshots:
        if (
            s.success
            and s.tool_name == definition.tool_name
            and str((s.arguments or {}).get(definition.id_argument)) == str(resource_id)
        ):
            return s
    return None


def build_card(card_code: str, resource_id: str, snapshots: tuple[ToolCallSnapshot, ...]) -> dict:
    """服务端拼装卡片 payload（模型永远不产出 URL/文案/数据）。"""
    definition = ACTION_CATALOG.get(card_code)
    if definition is None:
        raise AgentOutputValidationError(
            CorrectableErrorCode.UNVERIFIED_ACTION_RESOURCE, f"未知卡片类型 {card_code}"
        )
    snapshot = find_resource_snapshot(card_code, resource_id, snapshots)
    if snapshot is None or not isinstance(snapshot.result, dict):
        raise AgentOutputValidationError(
            CorrectableErrorCode.UNVERIFIED_ACTION_RESOURCE,
            f"{definition.label} 资源 {resource_id} 未在本轮成功查询",
        )
    data = snapshot.result
    if card_code == "ORDER_CARD":
        items = data.get("items") or []
        title = (items[0].get("title") if items else None) or data.get("order_id", "")
        return {
            "type": "order",
            "id": data.get("order_id", resource_id),
            "title": title,
            "attributes": {
                "status": data.get("status"),
                "amount": data.get("amount"),
                "created_at": data.get("created_at"),
            },
        }
    return {
        "type": "product",
        "id": data.get("product_id", resource_id),
        "title": data.get("title", ""),
        "attributes": {
            "price": data.get("price"),
            "description": data.get("description"),
        },
    }
