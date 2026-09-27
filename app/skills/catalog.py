"""技能目录（SPEC 7 章全文）。变更必须升级 settings.prompt_version。"""

from app.domain.enums import SkillCode
from app.skills.definition import SkillDefinition

SKILL_CATALOG: tuple[SkillDefinition, ...] = (
    SkillDefinition(
        code=SkillCode.ORDER,
        description="查订单列表、订单详情与当前状态",
        tools=("list_orders", "get_order"),
        guidance=(
            "查询入口：用户没给订单号时先用 list_orders（按当前用户），多单时让用户点选或报单号后缀。",
            "工具选择：订单状态/金额/收货信息用 get_order。",
            "可信依据：状态、金额、单号只能来自工具成功结果，禁止凭用户口述断言。",
            "边界处理：订单不存在时告知并建议核对单号，不得猜测其他订单。",
        ),
    ),
    SkillDefinition(
        code=SkillCode.LOGISTICS,
        description="订单发货状态、承运公司、运单号与物流轨迹",
        tools=("get_order", "get_logistics"),
        guidance=(
            "查询入口：无单号先 get_order 或 list_orders 定位订单。",
            "工具选择：轨迹用 get_logistics；get_logistics 无记录（404）时转述'暂无物流信息'。",
            "可信依据：承运公司、运单号、轨迹时间只能来自 get_logistics 成功结果。",
            "边界处理：不得预测送达时间，可引用 status_desc。",
        ),
    ),
    SkillDefinition(
        code=SkillCode.REFUND,
        description="为订单提交退款申请（需收集原因并经用户确认）",
        tools=("list_orders", "get_order", "request_refund_confirmation", "submit_refund_application"),
        guidance=(
            "查询入口：无单号先定位订单（list_orders/点选卡片）。",
            "工具选择：提交退款前必须 get_order 核实订单存在，且已问清退款原因。",
            "可信依据：复述订单号、金额必须来自 get_order 结果。",
            "边界处理：工具返回'已有进行中退款'时如实转述，不再重试提交。",
            "确认流程：核实订单与原因后调用 request_refund_confirmation 登记确认请求，"
            "然后在回复中复述订单号与原因并询问是否确认；用户明确同意后才调用 submit_refund_application。",
        ),
    ),
    SkillDefinition(
        code=SkillCode.PRODUCT,
        description="商品详情查询与相似商品推荐",
        tools=("get_product", "recommend_similar_products"),
        guidance=(
            "查询入口：有商品 ID 直接查；无 ID 请用户点选商品卡片。",
            "工具选择：详情用 get_product；推荐用 recommend_similar_products。",
            "可信依据：价格、库存状态只能来自工具成功结果。",
            "边界处理：推荐结果为占位数据时如实说明'以下为参考推荐'。",
        ),
    ),
    SkillDefinition(
        code=SkillCode.POLICY,
        description="退款政策、价保规则等平台政策问答",
        tools=("search_knowledge",),
        guidance=(
            "查询入口：政策类问题一律先 search_knowledge。",
            "工具选择：仅使用 search_knowledge，不得用业务工具回答政策问题。",
            "可信依据：政策条目必须引用 search_knowledge 返回的来源编号。",
            "边界处理：检索不到时如实告知并建议转人工，不得编造政策。",
        ),
    ),
)

_SKILL_INDEX: dict[SkillCode, SkillDefinition] = {s.code: s for s in SKILL_CATALOG}


def get_skill(code: SkillCode) -> SkillDefinition:
    return _SKILL_INDEX[code]


def render_index() -> str:
    """技能精简索引（未激活技能时随动态提示词注入）。"""
    return "\n".join(f"- {s.code}: {s.description}" for s in SKILL_CATALOG)
