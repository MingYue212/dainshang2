"""事实提取与比对（FR-402/403，AC-04）：三类事实必须有成功工具结果背书。"""

from app.harness.snapshot import ToolCallSnapshot
from app.rules.fact import FactCategory, FactChecker, FactExtractor

checker = FactChecker()


def _snap(order_data: dict, arguments: dict | None = None) -> ToolCallSnapshot:
    return ToolCallSnapshot(
        tool_call_id="c1",
        tool_name="get_order",
        arguments=arguments or {"order_id": "A20260408002"},
        result=order_data,
        success=True,
    )


def test_extract_identifiers():
    facts = FactExtractor.extract("订单 A20260408002 和退款单 R202604070001 已处理，运单 JD000123456789")
    ids = {f.value for f in facts if f.category is FactCategory.IDENTIFIER}
    assert {"A20260408002", "R202604070001", "JD000123456789"} <= ids


def test_extract_money_and_units():
    facts = FactExtractor.extract("退款金额为149.00元，共3件商品，总价¥8999")
    numbers = {f.value for f in facts if f.category is FactCategory.NUMBER}
    assert {"149.00", "3", "8999"} <= numbers


def test_extract_status_words():
    facts = FactExtractor.extract("您的订单正在运输中，包裹已签收的部分会显示派送中")
    statuses = {f.value for f in facts if f.category is FactCategory.STATUS}
    assert {"运输中", "已签收", "派送中"} <= statuses


def test_supported_money_decimal_equality():
    """149.00 与工具结果里的 149.0 数值等价（Decimal 比较）。"""
    snap = _snap({"order_id": "A20260408002", "amount": 149.0, "status": "运输中"})
    unsupported = checker.get_unsupported_facts("退款金额为149.00元。", (snap,))
    assert unsupported == ()


def test_unsupported_money_is_caught():
    snap = _snap({"order_id": "A20260408002", "amount": 149.0})
    unsupported = checker.get_unsupported_facts("退款金额为500元。", (snap,))
    assert any(f.value == "500" for f in unsupported)


def test_supported_identifier_from_arguments_and_result():
    snap = _snap(
        {"order_id": "A20260408002", "status": "运输中", "items": [{"product_id": "SKU10002"}]},
        arguments={"order_id": "A20260408002"},
    )
    unsupported = checker.get_unsupported_facts(
        "订单 A20260408002 正在运输中，包含商品 SKU10002。", (snap,)
    )
    assert unsupported == ()


def test_unsupported_status_is_caught():
    snap = _snap({"order_id": "A20260408002", "status": "运输中"})
    unsupported = checker.get_unsupported_facts("您的订单已完成。", (snap,))
    assert any(f.value == "已完成" for f in unsupported)


def test_status_matches_english_code_in_evidence():
    """退款状态在 18081 中是英文码（submitted），中文标签经映射可匹配。"""
    snap = ToolCallSnapshot(
        tool_call_id="c2",
        tool_name="submit_refund_application",
        arguments={"order_id": "A20260408002"},
        result={"request_type": "refund_application", "status": "submitted"},
        success=True,
    )
    unsupported = checker.get_unsupported_facts("您的退款申请已提交。", (snap,))
    assert unsupported == ()


def test_failed_tools_are_not_evidence():
    snap = ToolCallSnapshot(
        tool_call_id="c3",
        tool_name="get_order",
        arguments={"order_id": "A20260408002"},
        result={"message": "订单不存在"},
        success=False,
    )
    unsupported = checker.get_unsupported_facts("订单 A20260408002 已完成。", (snap,))
    assert len(unsupported) >= 2  # 编号与状态都无背书


def test_no_facts_passes():
    assert checker.get_unsupported_facts("您好，请问有什么可以帮您？", ()) == ()
