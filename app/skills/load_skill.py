"""load_skill 工具（SPEC 6.2/7 章）：更新 active_skill_code 并把技能定义写进消息轨迹。"""

from typing import Annotated

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.domain.enums import SkillCode, ToolCategory
from app.harness.runtime import AgentExecutionState, AgentRuntimeContext
from app.skills.catalog import get_skill
from app.tools.envelope import OK_CODE, ToolResult
from app.tools.registry import TOOL_CATALOG, ToolDefinition


@tool
async def load_skill(
    skill_code: Annotated[
        str, "与当前用户问题最匹配的客服领域技能编码（如 REFUND_SERVICE）"
    ],
    runtime: ToolRuntime[AgentRuntimeContext, AgentExecutionState],
) -> Command:
    """加载客服领域技能并更新当前 Agent 的能力范围。技能已激活时不要重复调用本工具。"""
    from app.infra.db import SessionLocal
    from app.memory.repository import save_message_tool_call
    from app.harness.tool_executor import current_run_id

    # 宽容解析：模型可能传 "REFUND" 这类短码，映射回完整枚举值
    raw = (skill_code or "").strip().upper()
    for candidate in (raw, f"{raw}_SERVICE" if raw and "_" not in raw else raw):
        try:
            resolved = SkillCode(candidate)
            break
        except ValueError:
            continue
    else:
        raise ValueError(
            f"未知技能编码 {skill_code!r}，可用值：{[s.value for s in SkillCode]}"
        )

    skill = get_skill(resolved)
    result_json = ToolResult[dict](
        success=True,
        code=OK_CODE,
        message="客服领域技能已加载",
        data=skill.model_dump(mode="json"),
    ).model_dump_json()

    # 快照落库：load_skill 也计入调用预算与观测（否则会成为"隐形调用"）
    run_id = current_run_id.get()
    if run_id:
        try:
            async with SessionLocal() as session:
                await save_message_tool_call(
                    session,
                    run_id=run_id,
                    tool_call_id=runtime.tool_call_id,
                    tool_name="load_skill",
                    arguments={"skill_code": str(resolved)},
                    result={"skill": str(resolved), "description": skill.description},
                )
                await session.commit()
        except Exception:  # noqa: BLE001——观测落库失败不影响技能加载
            pass

    return Command(
        update={
            "active_skill_code": resolved,
            "messages": [
                ToolMessage(content=result_json, tool_call_id=runtime.tool_call_id)
            ],
        }
    )


TOOL_CATALOG.register(ToolDefinition(tool=load_skill, category=ToolCategory.GUIDANCE))
