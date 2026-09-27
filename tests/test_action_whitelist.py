"""页面动作白名单（FR-205）：未知类型拒绝、未核实资源拒绝、服务端拼装字段正确。"""

import pytest

from app.errors import AgentOutputValidationError, CorrectableErrorCode
from app.harness.snapshot import ToolCallSnapshot
from app.tools.action import ACTION_CATALOG, build_card, find_resource_snapshot
from app.validator.action import PageActionValidator

ORDER_DATA = {
    "order_id": "A20260408002",
    "status": "运输中",
    "amount": 149.0,
    "created_at": "2026-04-08T15:30:00",
    "items": [{"product_id": "SKU10002", "title": "小米恒温电热水壶 3", "quantity": 1, "price": 149.0}],
}
PRODUCT_DATA = {
    "product_id": "SKU10002",
    "title": "小米恒温电热水壶 3",
    "description": "3L 大容量",
    "price": 149.0,
    "stock_status": "在售",
}


def _order_snap() -> ToolCallSnapshot:
    return ToolCallSnapshot(
        tool_call_id="c1",
        tool_name="get_order",
        arguments={"order_id": "A20260408002"},
        result=ORDER_DATA,
        success=True,
    )


def test_catalog_whitelist():
    assert set(ACTION_CATALOG) == {"ORDER_CARD", "PRODUCT_CARD"}


def test_find_resource_snapshot_matches_arguments():
    assert find_resource_snapshot("ORDER_CARD", "A20260408002", (_order_snap(),)) is not None
    assert find_resource_snapshot("ORDER_CARD", "A20260410001", (_order_snap(),)) is None
    assert find_resource_snapshot("PRODUCT_CARD", "A20260408002", (_order_snap(),)) is None


def test_build_order_card_fields():
    card = build_card("ORDER_CARD", "A20260408002", (_order_snap(),))
    assert card["type"] == "order"
    assert card["id"] == "A20260408002"
    assert card["title"] == "小米恒温电热水壶 3"
    assert card["attributes"]["status"] == "运输中"
    assert card["attributes"]["amount"] == 149.0


def test_build_product_card_fields():
    snap = ToolCallSnapshot(
        tool_call_id="c2",
        tool_name="get_product",
        arguments={"product_id": "SKU10002"},
        result=PRODUCT_DATA,
        success=True,
    )
    card = build_card("PRODUCT_CARD", "SKU10002", (snap,))
    assert card["type"] == "product"
    assert card["attributes"]["price"] == 149.0
    assert card["attributes"]["description"] == "3L 大容量"


def test_unverified_resource_rejected():
    with pytest.raises(AgentOutputValidationError) as ei:
        build_card("ORDER_CARD", "A20260410001", (_order_snap(),))
    assert ei.value.code is CorrectableErrorCode.UNVERIFIED_ACTION_RESOURCE


def test_validator_rejects_unknown_card():
    from app.agent.output import PageActionRequest

    with pytest.raises(AgentOutputValidationError):
        PageActionValidator.validate(
            PageActionRequest(card_code="ORDER_CARD", resource_id="A20260410001"),
            (_order_snap(),),
        )


def test_validator_passes_verified_card():
    from app.agent.output import PageActionRequest

    PageActionValidator.validate(
        PageActionRequest(card_code="ORDER_CARD", resource_id="A20260408002"),
        (_order_snap(),),
    )
