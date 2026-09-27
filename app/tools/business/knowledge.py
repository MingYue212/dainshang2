"""知识检索：Provider 接口 + 固定 FAQ 占位实现（PRD FR-206 两档配置，换向量库只换 Provider）。

条目为占位数据（口径参考电商平台通用政策），上线前需替换为真实政策库。
"""

from typing import Protocol

from pydantic import BaseModel, Field, TypeAdapter
from langchain_core.tools import tool

from app.domain.enums import ToolCategory
from app.harness.tool_executor import execute_tool
from app.tools.registry import TOOL_CATALOG, ToolDefinition


class KnowledgeItem(BaseModel):
    id: str
    title: str
    content: str


class KnowledgeData(BaseModel):
    items: list[KnowledgeItem] = []
    source: str = "faq-placeholder"


KNOWLEDGE_ADAPTER = TypeAdapter(KnowledgeData)


class KnowledgeProvider(Protocol):
    async def retrieve(self, query: str) -> list[KnowledgeItem]: ...


FAQ_ENTRIES: list[KnowledgeItem] = [
    KnowledgeItem(
        id="FAQ-REFUND-01",
        title="退款审核时效",
        content="退款申请提交后，平台将在 1-3 个工作日内完成审核，审核结果会通过站内消息通知。（占位数据）",
    ),
    KnowledgeItem(
        id="FAQ-REFUND-02",
        title="退款到账时间",
        content="退款审核通过后，款项将在 3-7 个工作日内按原支付路径退回。（占位数据）",
    ),
    KnowledgeItem(
        id="FAQ-POLICY-01",
        title="七天无理由退货",
        content="自签收之日起 7 天内，商品未使用且不影响二次销售的，可申请无理由退货。（占位数据）",
    ),
    KnowledgeItem(
        id="FAQ-POLICY-02",
        title="价保规则",
        content="签收后 15 天内同一商品出现降价，可申请差价补偿，活动价格以订单页展示为准。（占位数据）",
    ),
    KnowledgeItem(
        id="FAQ-SHIPPING-01",
        title="发货时效",
        content="现货商品一般在付款后 48 小时内发货，预售商品以商品页标注时间为准。（占位数据）",
    ),
]


class FAQProvider:
    """固定 FAQ 占位实现：朴素关键词匹配。换真向量库时实现同一接口即可。"""

    async def retrieve(self, query: str) -> list[KnowledgeItem]:
        query_norm = query.strip()
        if not query_norm:
            return []
        hit: list[KnowledgeItem] = []
        for entry in FAQ_ENTRIES:
            keywords = {*(entry.title or "").split(), *entry.id.split("-")[:1]}
            text = f"{entry.title}{entry.content}"
            if any(k and k in query_norm for k in keywords) or _keyword_overlap(query_norm, text):
                hit.append(entry)
        return hit or []


def _keyword_overlap(query: str, text: str) -> bool:
    # 极简占位：查询里的任意 2 字片段命中正文即算命中（真实现由向量库承担）
    return any(query[i : i + 2] in text for i in range(max(len(query) - 1, 0)))


_provider: KnowledgeProvider = FAQProvider()


def set_knowledge_provider(provider: KnowledgeProvider) -> None:
    global _provider
    _provider = provider


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="政策问题关键词，如：退款多久到账")


@tool("search_knowledge", args_schema=SearchKnowledgeArgs)
async def search_knowledge(query: str) -> str:
    """检索平台政策知识库（退款时效、到账时间、价保、退货、发货等）。

    回答政策类问题时必须引用返回条目的编号（id）；检索不到时如实告知并建议转人工。
    """
    return await execute_tool(
        tool_name="search_knowledge",
        arguments={"query": query},
        runner=lambda: _retrieve_data(query),
        schema=KNOWLEDGE_ADAPTER,
    )


async def _retrieve_data(query: str) -> dict:
    items = await _provider.retrieve(query)
    return {"items": [i.model_dump() for i in items], "source": "faq-placeholder"}


TOOL_CATALOG.register(
    ToolDefinition(tool=search_knowledge, category=ToolCategory.KNOWLEDGE)
)
