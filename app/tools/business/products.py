"""商品工具：get_product（详情）与 recommend_similar_products（18081 无推荐端点，与 V1 同口径取详情 + 占位推荐）。"""

from pydantic import BaseModel, Field, TypeAdapter
from langchain_core.tools import tool

from app.domain.enums import ToolCategory
from app.harness.tool_executor import execute_tool
from app.infra.commerce_client import get_commerce_client
from app.tools.registry import TOOL_CATALOG, ToolDefinition


class ProductData(BaseModel):
    product_id: str
    title: str
    description: str | None = None
    price: float
    stock_status: str | None = None
    cover_url: str | None = None
    attributes: dict = {}


class Recommendation(BaseModel):
    product_id: str
    title: str
    price: float
    reason: str


class RecommendData(BaseModel):
    base_product_id: str
    note: str
    recommendations: list[Recommendation] = []


PRODUCT_ADAPTER = TypeAdapter(ProductData)
RECOMMEND_ADAPTER = TypeAdapter(RecommendData)


class ProductArgs(BaseModel):
    product_id: str = Field(pattern=r"^SKU\d+$", description="商品编号，如 SKU10002")


@tool("get_product", args_schema=ProductArgs)
async def get_product(product_id: str) -> str:
    """查询商品详情：标题、描述、价格与库存状态。"""
    client = get_commerce_client()
    return await execute_tool(
        tool_name="get_product",
        arguments={"product_id": product_id},
        runner=lambda: client.get_data(f"/products/{product_id}"),
        schema=PRODUCT_ADAPTER,
    )


@tool("recommend_similar_products", args_schema=ProductArgs)
async def recommend_similar_products(product_id: str) -> str:
    """推荐与指定商品相似的参考商品。

    当前推荐为占位数据（与业务后端能力一致），回复时必须如实说明"以下为参考推荐"。
    """
    client = get_commerce_client()

    async def runner() -> dict:
        data = await client.get_data(f"/products/{product_id}")
        return {
            "base_product_id": data["product_id"],
            "note": "暂无真实协同推荐数据，以下为同类参考（占位数据）",
            "recommendations": [
                {
                    "product_id": data["product_id"],
                    "title": data["title"],
                    "price": data["price"],
                    "reason": "与所选商品同款系的参考选项（占位数据）",
                }
            ],
        }

    return await execute_tool(
        tool_name="recommend_similar_products",
        arguments={"product_id": product_id},
        runner=runner,
        schema=RECOMMEND_ADAPTER,
    )


TOOL_CATALOG.register(ToolDefinition(tool=get_product, category=ToolCategory.BUSINESS))
TOOL_CATALOG.register(
    ToolDefinition(tool=recommend_similar_products, category=ToolCategory.BUSINESS)
)
