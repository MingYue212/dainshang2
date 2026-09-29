"""流式 content 提取器（FR-702 / SPEC 14.4）：状态机在任意分片粒度下都能提取。"""

import pytest

from app.harness.streaming import _ContentFieldStream, ContentStreamHandler

ARGS = (
    '{"reply_type": "ANSWER", "content": "退款金额为149.00元，已提交申请。", '
    '"page_action": {"card_code": "ORDER_CARD", "resource_id": "A20260408002"}}'
)
CONTENT = "退款金额为149.00元，已提交申请。"


def _feed_all(fragments) -> str:
    s = _ContentFieldStream()
    out: list[str] = []
    for f in fragments:
        out.extend(s.feed(f))
    return "".join(out)


def test_single_chunk():
    assert _feed_all([ARGS]) == CONTENT


def test_char_by_char():
    assert _feed_all(list(ARGS)) == CONTENT


def test_random_chunk_sizes():
    sizes = [1, 7, 3, 11, 2, 5]
    frags, i = [], 0
    k = 0
    while i < len(ARGS):
        n = sizes[k % len(sizes)]
        frags.append(ARGS[i : i + n])
        i += n
        k += 1
    assert _feed_all(frags) == CONTENT


def test_escapes_decoded():
    args = r'{"content": "订单 \"A\" 已\n签收 \\ 完成"}'
    assert _feed_all([args]) == '订单 "A" 已\n签收 \\ 完成'


def test_unicode_escape():
    args = '{"content": "\\u4f60\\u597d"}'
    assert _feed_all([args]) == "你好"


def test_escape_split_across_fragments():
    args = '{"content": "A\\u4f60"}'  # \u 转义跨分片（你 = U+4F60）
    s = _ContentFieldStream()
    out = s.feed(args[:16]) + s.feed(args[16:])
    assert "".join(out) == "A你"


def test_nested_object_does_not_shadow_content():
    """page_action 等嵌套对象里的字符串不干扰顶层 content 提取。"""
    args = '{"page_action": {"note": "has \\"content\\" inside: {brackets}"}, "content": "OK"}'
    assert _feed_all([args]) == "OK"


def test_no_content_key_yields_nothing():
    assert _feed_all(['{"reply_type": "DECLINE"}']) == ""


def test_content_first_order():
    assert _feed_all(['{"content": "你好", "reply_type": "ANSWER"}']) == "你好"


@pytest.mark.asyncio
async def test_handler_only_streams_structured_tool():
    """非 AgentOutput 工具调用的 args 不产生 delta（中间工具调用不外泄）。"""
    sent: list[str] = []

    async def send(delta: str) -> None:
        sent.append(delta)

    class FakeChunk:
        def __init__(self, tool_call_chunks):
            self.message = type("M", (), {"tool_call_chunks": tool_call_chunks})()

    h = ContentStreamHandler(send)
    # 业务工具调用的 args（含 content 字样的 JSON）不应被外泄
    await h.on_llm_new_token("", chunk=FakeChunk([
        {"name": "get_order", "args": '{"order_id": "A20260408002"}', "index": 0}
    ]))
    # 结构化输出工具的 args 正常提取
    await h.on_llm_new_token("", chunk=FakeChunk([
        {"name": "AgentOutput", "args": '{"reply_type": "ANSWER", "con', "index": 1}
    ]))
    await h.on_llm_new_token("", chunk=FakeChunk([
        {"name": None, "args": 'tent": "你好呀", "page_action": null}', "index": 1}
    ]))
    assert sent and "".join(sent) == "你好呀"
