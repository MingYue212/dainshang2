"""技能定义（SPEC 7 章）：guidance 四段式——查询入口/工具选择/可信依据/边界处理。"""

from pydantic import BaseModel, ConfigDict

from app.domain.enums import SkillCode


class SkillDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: SkillCode
    description: str
    guidance: tuple[str, ...]
    tools: tuple[str, ...]
