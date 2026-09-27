"""工具注册表（SPEC 8 章）：ToolDefinition 打数据类别标签，供技能收窄与事实检验使用。"""

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.domain.enums import ToolCategory


@dataclass(frozen=True)
class ToolDefinition:
    tool: BaseTool
    category: ToolCategory


class ToolCatalog:
    def __init__(self) -> None:
        self._items: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._items[definition.tool.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._items.get(name)

    def get_agent_tools(self) -> list[BaseTool]:
        return [d.tool for d in self._items.values()]

    def names(self) -> list[str]:
        return list(self._items)


TOOL_CATALOG = ToolCatalog()
