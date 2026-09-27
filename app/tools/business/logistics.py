"""物流工具：映射 18081 GET /orders/{order_id}/logistics（无记录返回 404 → BUSINESS 失败）。"""

from pydantic import BaseModel, Field, TypeAdapter
from langchain_core.tools import tool

from app.domain.enums import ToolCategory
from app.harness.tool_executor import execute_tool
from app.infra.commerce_client import get_commerce_client
from app.tools.registry import TOOL_CATALOG, ToolDefinition


class LogisticsTrace(BaseModel):
    time: str | None = None
    desc: str | None = None


class LogisticsData(BaseModel):
    order_id: str
    logistics_company: str | None = None
    tracking_number: str | None = None
    status: str | None = None
    status_desc: str | None = None
    traces: list[LogisticsTrace] = []


LOGISTICS_ADAPTER = TypeAdapter(LogisticsData)


class GetLogisticsArgs(BaseModel):
    order_id: str = Field(pattern=r"^[ABC]\d{11}$", description="订单号，如 A20260408002")


@tool("get_logistics", args_schema=GetLogisticsArgs)
async def get_logistics(order_id: str) -> str:
    """查询订单的承运公司、运单号与物流轨迹。

    工具返回"暂无物流信息"时如实转述，不得预测送达时间。
    """
    client = get_commerce_client()
    return await execute_tool(
        tool_name="get_logistics",
        arguments={"order_id": order_id},
        runner=lambda: client.get_data(f"/orders/{order_id}/logistics"),
        schema=LOGISTICS_ADAPTER,
    )


TOOL_CATALOG.register(ToolDefinition(tool=get_logistics, category=ToolCategory.BUSINESS))
