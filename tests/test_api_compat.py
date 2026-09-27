"""API 契约兼容（FR-701/703）：与 V1 交互模型字段级 round-trip（契约速查 A1/A3）。"""

from app.api.schemas import (
    BotMsgResponse,
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    HistoryMsgResponse,
)

V1_ORDER_OBJECT = {
    "type": "order",
    "id": "A20260408002",
    "title": "小米恒温电热水壶 3",
    "attributes": {"status": "运输中", "amount": 149.00},
}


def test_chat_request_parses_v1_payload():
    req = ChatRequest.model_validate(
        {"sender_id": "u1001", "msg_id": "m-1", "text": "我要退款", "object": V1_ORDER_OBJECT}
    )
    assert req.sender_id == "u1001"
    assert req.text == "我要退款"
    assert req.object is not None
    assert req.object.type == "order"
    assert req.object.attributes["amount"] == 149.00


def test_chat_request_defaults_match_v1():
    req = ChatRequest.model_validate({"sender_id": "u1001"})
    assert req.msg_id is None
    assert req.text is None
    assert req.object is None


def test_chat_request_accepts_object_without_text():
    """前端点选卡片时只上行 object（ServiceChat.vue:245-273 口径）。"""
    req = ChatRequest.model_validate({"sender_id": "u1001", "object": V1_ORDER_OBJECT})
    assert req.text is None
    assert req.object.id == "A20260408002"


def test_chat_response_shape_matches_v1():
    resp = ChatResponse(
        sender_id="u1001", msg_id="m-1", msgs=[BotMsgResponse(text="好的")]
    )
    data = resp.model_dump(mode="json")
    assert set(data) == {"sender_id", "msg_id", "msgs"}
    assert set(data["msgs"][0]) == {"text", "object"}
    assert data["msgs"][0]["object"] is None


def test_chat_response_carries_object_card():
    """V2 增量兼容：bot 消息可携带卡片，前端已支持渲染（契约速查 C1）。"""
    resp = ChatResponse(
        sender_id="u1001",
        msg_id="m-1",
        msgs=[BotMsgResponse(object=V1_ORDER_OBJECT)],
    )
    data = resp.model_dump(mode="json")
    assert data["msgs"][0]["object"]["type"] == "order"


def test_history_msg_shape_matches_v1():
    msg = HistoryMsgResponse(session_id="u1001", role="bot", create_time=1790000000.0, text="hi")
    data = msg.model_dump(mode="json")
    assert set(data) == {"session_id", "role", "create_time", "text", "object"}
    assert data["session_id"] == "u1001"


def test_history_response_wraps_msgs():
    resp = ChatHistoryResponse(sender_id="u1001", msgs=[])
    assert resp.model_dump(mode="json") == {"sender_id": "u1001", "msgs": []}
