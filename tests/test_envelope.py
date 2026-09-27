"""信封与失败分类（FR-201，AC-12）：三档失败产物锁定，无异常逃逸。"""

import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.domain.enums import FailureType
from app.harness.tool_executor import classify_failure
from app.infra.commerce_client import CommerceError
from app.tools.envelope import TOOL_FAILED_CODE, ToolResult


def _validation_error() -> ValidationError:
    class _M(BaseModel):
        a: int

    with pytest.raises(ValidationError) as exc_info:
        _M.model_validate({"a": "not-an-int"})
    return exc_info.value


def test_commerce_error_is_business():
    failure_type, message = classify_failure(CommerceError("该订单已有进行中的退款申请"))
    assert failure_type is FailureType.BUSINESS
    assert message == "该订单已有进行中的退款申请"


def test_validation_error_is_contract():
    failure_type, message = classify_failure(_validation_error())
    assert failure_type is FailureType.CONTRACT
    assert message


def test_timeout_is_service_call():
    failure_type, _ = classify_failure(httpx.ConnectTimeout("timed out"))
    assert failure_type is FailureType.SERVICE_CALL


def test_http_error_is_service_call():
    failure_type, _ = classify_failure(httpx.ConnectError("refused"))
    assert failure_type is FailureType.SERVICE_CALL


def test_unknown_error_is_service_call():
    failure_type, _ = classify_failure(RuntimeError("boom"))
    assert failure_type is FailureType.SERVICE_CALL


def test_toolresult_ok_shape():
    payload = json.loads(
        ToolResult(success=True, code="OK", message="ok", data={"order_id": "A20260408002"}).model_dump_json()
    )
    assert payload == {
        "success": True,
        "code": "OK",
        "failure_type": None,
        "message": "ok",
        "data": {"order_id": "A20260408002"},
    }


def test_toolresult_fail_shape():
    payload = json.loads(
        ToolResult(
            success=False,
            code=TOOL_FAILED_CODE,
            failure_type=FailureType.BUSINESS.value,
            message="订单不存在",
            data=None,
        ).model_dump_json()
    )
    assert payload["success"] is False
    assert payload["code"] == "EC-3001"
    assert payload["failure_type"] == "BUSINESS"
    assert payload["data"] is None
