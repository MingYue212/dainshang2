"""技能目录与工具注册完整性（FR-301/302/303）。"""

import app.skills.load_skill  # noqa: F401——与工厂一致地触发 load_skill 注册
from app.domain.enums import SkillCode
from app.skills.catalog import SKILL_CATALOG, get_skill, render_index
from app.tools.registry import TOOL_CATALOG


def test_five_skills_defined():
    assert {s.code for s in SKILL_CATALOG} == {
        SkillCode.PRODUCT,
        SkillCode.ORDER,
        SkillCode.LOGISTICS,
        SkillCode.REFUND,
        SkillCode.POLICY,
    }


def test_guidance_four_stage_style():
    for skill in SKILL_CATALOG:
        assert len(skill.guidance) >= 4
        joined = "".join(skill.guidance)
        for stage in ("查询入口", "工具选择", "可信依据", "边界处理"):
            assert stage in joined, f"{skill.code} 缺少 {stage} 段"


def test_skill_tools_all_registered():
    """技能引用的每个工具都必须已在 TOOL_CATALOG 注册（含 load_skill）。"""
    assert "load_skill" in TOOL_CATALOG.names()
    for skill in SKILL_CATALOG:
        for tool_name in skill.tools:
            assert tool_name in TOOL_CATALOG.names(), f"{skill.code} 引用未注册工具 {tool_name}"


def test_get_skill_and_index():
    skill = get_skill(SkillCode.REFUND)
    assert skill.code is SkillCode.REFUND
    index = render_index()
    for s in SKILL_CATALOG:
        assert s.code in index
