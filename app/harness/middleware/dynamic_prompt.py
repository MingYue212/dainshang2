"""动态提示词中间件（SPEC 6.1，课程 dynamic_prompt.py 同构）：每次模型调用按当前技能重渲染。"""

from langchain.agents.middleware import ModelRequest, dynamic_prompt

from app.agent.prompts import BASE_PROMPT
from app.domain.enums import SkillCode
from app.skills.catalog import SKILL_CATALOG, get_skill
from app.tools.action import ACTION_CATALOG, render_action_index


def render_skill_prompt(active_skill_code: SkillCode | None) -> str:
    """根据当前状态生成 Skill 提示词。"""
    if active_skill_code is None:
        return (
            "【动态 Skill 路由】\n"
            "用户询问商品、订单、物流、售后或平台政策时，先调用 load_skill 加载对应领域；普通寒暄可以直接回答。\n"
            "用户同时询问多个领域时，一次只处理一个 Skill；完成当前领域所需查询后，再切换到下一个 Skill。\n"
            f"可用 Skill：\n{_index()}"
        )
    skill = get_skill(active_skill_code)
    guidance = "\n".join(f"- {item}" for item in skill.guidance)
    return (
        f"【当前 Skill：{skill.code}】\n"
        f"{guidance}\n"
        "用户同时询问多个领域时，一次只处理一个 Skill；完成当前领域所需查询后，再切换到下一个 Skill。"
    )


def _index() -> str:
    return "\n".join(f"- {s.code}: {s.description}" for s in SKILL_CATALOG)


def render_support_prompt(active_skill_code: SkillCode | None) -> str:
    """按当前 Skill 生成完整系统提示词：全局层 + 技能层 + 动作索引层。"""
    skill_prompt = render_skill_prompt(active_skill_code)
    action_prompt = f"【白名单页面动作】\n{render_action_index()}"
    return f"{BASE_PROMPT}\n\n{skill_prompt}\n\n{action_prompt}"


@dynamic_prompt
def support_prompt(request: ModelRequest) -> str:
    """为每次模型调用生成当前能力范围内的系统提示词。"""
    active = request.state.get("active_skill_code")
    if isinstance(active, str):
        active = SkillCode(active)
    return render_support_prompt(active)
