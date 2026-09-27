"""退款确认门（FR-204/13.3）：无待确认/订单不一致/超时/放行 四分支。"""

from datetime import datetime, timedelta

from app.tools.business.refund import check_pending

NOW = datetime(2026, 9, 27, 21, 0, 0)


def _pending(order_id="A20260408002"):
    return {"pending_action": "refund", "order_id": order_id, "reason": "杯盖裂了漏水"}


def test_no_pending_rejected():
    assert check_pending(None, None, "A20260408002", NOW, 30) is not None
    assert check_pending({"pending_action": "other"}, NOW, "A20260408002", NOW, 30) is not None


def test_order_mismatch_rejected():
    msg = check_pending(_pending(), NOW, "A20260410001", NOW, 30)
    assert "不一致" in msg


def test_expired_rejected():
    stale = NOW - timedelta(minutes=31)
    msg = check_pending(_pending(), stale, "A20260408002", NOW, 30)
    assert "超时" in msg


def test_valid_pending_passes():
    fresh = NOW - timedelta(minutes=5)
    assert check_pending(_pending(), fresh, "A20260408002", NOW, 30) is None
