"""订单查询工具：映射 18081 GET /orders/{order_id}（契约核实见 SPEC 14/8 章）。"""

from pydantic import BaseModel, Field, TypeAdapter
from langchain_core.tools import tool

from app.harness.tool_executor import execute_tool
from app.infra.commerce_client import get_commerce_client
from app.tools.registry import TOOL_CATALOG, ToolDefinition
from app.domain.enums import ToolCategory


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


ORDER_ADAPTER = TypeAdapter(OrderData)


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


TOOL_CATALOG.register(ToolDefinition(tool=get_order, category=ToolCategory.BUSINESS))
