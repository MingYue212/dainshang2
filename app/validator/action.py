"""页面动作校验（SPEC 9.2/12）：白名单 + 资源必须在本 Run 被成功查询。"""

from app.errors import AgentOutputValidationError, CorrectableErrorCode
from app.harness.snapshot import ToolCallSnapshot
from app.tools.action import find_resource_snapshot


class PageActionValidator:
    @staticmethod
    def validate(page_action, snapshots: tuple[ToolCallSnapshot, ...]) -> None:
        """page_action 不合法即抛可纠正错误；合法由服务端负责拼装卡片。"""
        if page_action is None:
            return
        definition_found = find_resource_snapshot(
            page_action.card_code, page_action.resource_id, snapshots
        )
        if definition_found is None:
            raise AgentOutputValidationError(
                CorrectableErrorCode.UNVERIFIED_ACTION_RESOURCE,
                f"{page_action.card_code} 资源 {page_action.resource_id} 未在本轮被成功查询",
            )
