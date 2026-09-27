"""订单工具：get_order（订单详情）与 list_orders（按用户查订单列表，18081 已证实存在）。"""

from pydantic import BaseModel, Field, TypeAdapter
from langchain_core.tools import tool

from app.domain.enums import ToolCategory
from app.harness.tool_executor import current_conversation_id, execute_tool
from app.infra.commerce_client import get_commerce_client
from app.tools.registry import TOOL_CATALOG, ToolDefinition


class GetOrderArgs(BaseModel):
    order_id: str = Field(pattern=r"^[ABC]\d{11}$", description="订单号，如 A20260408002")


class OrderItem(BaseModel):
    product_id: str
    title: str
    quantity: int
    price: float


class OrderData(BaseModel):
    order_id: str
    status: str
    status_desc: str | None = None
    amount: float
    created_at: str | None = None
    receiver_name: str | None = None
    receiver_phone_masked: str | None = None
    receiver_address: str | None = None
    items: list[OrderItem] = []


class OrderSummary(BaseModel):
    order_id: str
    title: str
    status: str
    amount: float
    created_at: str | None = None
    cover_url: str | None = None


class UserOrdersData(BaseModel):
    user_id: str
    orders: list[OrderSummary] = []


ORDER_ADAPTER = TypeAdapter(OrderData)
USER_ORDERS_ADAPTER = TypeAdapter(UserOrdersData)


@tool("get_order", args_schema=GetOrderArgs)
async def get_order(order_id: str) -> str:
    """查询订单详情：状态、金额、收货信息与商品明细。

    回答任何订单相关事实（状态/金额/单号）之前必须先调用本工具核实，
    禁止凭用户口述或记忆回答订单信息。
    """
    client = get_commerce_client()
    return await execute_tool(
        tool_name="get_order",
        arguments={"order_id": order_id},
        runner=lambda: client.get_data(f"/orders/{order_id}"),
        schema=ORDER_ADAPTER,
    )


@tool("list_orders")
async def list_orders() -> str:
    """查询当前用户的订单列表（含订单号、标题、状态与金额）。

    用户没有提供订单号时，先用本工具定位订单；结果为空时请用户核对账号。
    """
    conversation_id = current_conversation_id.get()
    client = get_commerce_client()
    if not conversation_id:
        return await execute_tool(
            tool_name="list_orders",
            arguments={},
            runner=lambda: _fail_no_user(),
            schema=USER_ORDERS_ADAPTER,
        )
    return await execute_tool(
        tool_name="list_orders",
        arguments={"user_id": conversation_id},
        runner=lambda: client.get_data(f"/users/{conversation_id}/orders"),
        schema=USER_ORDERS_ADAPTER,
    )


async def _fail_no_user() -> dict:
    from app.infra.commerce_client import CommerceError

    raise CommerceError("无法识别当前用户，请重新进入会话")


TOOL_CATALOG.register(ToolDefinition(tool=get_order, category=ToolCategory.BUSINESS))
TOOL_CATALOG.register(ToolDefinition(tool=list_orders, category=ToolCategory.BUSINESS))
