"""工具调用快照（课程 tools/snapshot.py 同构）：只读冻结视图，供校验器与事实检验使用。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCallSnapshot:
    tool_call_id: str
    tool_name: str
    arguments: dict = field(default_factory=dict)
    result: dict | None = None
    success: bool = False
    failure_type: str | None = None
