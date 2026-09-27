"""工具结果统一信封（SPEC 5.2）：模型永远收到结构化成败，永远收不到异常。"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

OK_CODE = "OK"
TOOL_FAILED_CODE = "EC-3001"
TOOL_LIMIT_CODE = "EC-3002"


class ToolResult(BaseModel, Generic[T]):
    success: bool
    code: str
    failure_type: str | None = None
    message: str
    data: T | None = None
