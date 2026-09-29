"""真流式（M3，SPEC 14.4）：从 ToolStrategy 结构化输出的 args 流中增量提取 content。

原理：response_format=ToolStrategy(AgentOutput) 时，最终回答以 AgentOutput 工具调用的
JSON 参数形式流式返回（{"reply_type":..., "content":"...", ...}）。ContentStreamHandler
挂在 on_llm_new_token 上，用字符级状态机只把 content 字段的**解码后文本**增量回调出去——
结构化输出的 JSON 骨架对前端完全透明。

解析失败/模型未流式 → 无 delta，WS 仍会收到完整 bot_message（V1 兼容路径，优雅降级）。
"""

import json
from collections.abc import Awaitable, Callable

from langchain_core.callbacks import BaseCallbackHandler

STRUCTURED_TOOL_NAME = "AgentOutput"

# ---- 字符级状态机：提取顶层 "content" 字符串值 ---------------------------------


class _ContentFieldStream:
    """feed() 喂入 args 片段，返回解码后的 content 增量。"""

    _WHITESPACE = " \t\r\n"

    def __init__(self) -> None:
        self._state = "HUNT_KEY"      # HUNT_KEY/IN_KEY/HUNT_COLON/HUNT_VALUE/
        #                               STREAM_STR/SKIP_STR/SKIP_PRIM/SKIP_NESTED/AFTER/DONE
        self._key_buf: list[str] = []
        self._depth = 0               # 嵌套深度（HUNT_VALUE 遇 { [ 时进入 SKIP_NESTED）
        self._esc: str | None = None  # 转义状态：None / "u" / 已收集的 hex 字符
        self._esc_buf: list[str] = []
        self._done = False

    def feed(self, fragment: str) -> list[str]:
        out: list[str] = []
        if self._done:
            return out
        for ch in fragment:
            out.extend(self._step(ch))
            if self._done and self._state != "STREAM_STR":
                break
        return out

    def _step(self, ch: str) -> list[str]:
        state = self._state
        if state == "HUNT_KEY":
            if ch == '"':
                self._state = "IN_KEY"
                self._key_buf = []
            elif ch == "}":
                self._done = True
        elif state == "IN_KEY":
            if self._esc is not None:
                self._key_buf.extend(self._feed_escape(ch))
            elif ch == "\\":
                self._esc = "\\"
            elif ch == '"':
                self._state = "HUNT_COLON"
            else:
                self._key_buf.append(ch)
        elif state == "HUNT_COLON":
            if ch == ":":
                self._state = "HUNT_VALUE"
        elif state == "HUNT_VALUE":
            if ch == '"':
                key = "".join(self._key_buf)
                if key == "content" and self._depth == 0:
                    self._state = "STREAM_STR"
                else:
                    self._state = "SKIP_STR"
            elif ch in "{[":
                self._depth += 1
                self._state = "SKIP_NESTED"
            elif ch not in self._WHITESPACE:
                self._state = "SKIP_PRIM"
        elif state == "STREAM_STR":
            return self._stream_char(ch)
        elif state == "SKIP_STR":
            if self._esc is not None:
                self._feed_escape(ch)
            elif ch == "\\":
                self._esc = "\\"
            elif ch == '"':
                self._state = "AFTER"
        elif state == "SKIP_PRIM":
            if ch in ",}":
                self._state = "AFTER"
                if ch == "}":
                    self._done = True
        elif state == "SKIP_NESTED":
            if self._esc is not None:
                self._feed_escape(ch)
            elif ch == "\\":
                self._esc = "\\"
            elif ch == '"':
                self._state = "SKIP_STR_NESTED"
            elif ch in "{[":
                self._depth += 1
            elif ch in "}]":
                self._depth -= 1
                if self._depth == 0:
                    self._state = "AFTER"
        elif state == "SKIP_STR_NESTED":
            if self._esc is not None:
                self._feed_escape(ch)
            elif ch == "\\":
                self._esc = "\\"
            elif ch == '"':
                self._state = "SKIP_NESTED"
        elif state == "AFTER":
            if ch == ",":
                self._state = "HUNT_KEY"
            elif ch == "}":
                self._done = True
        return []

    def _stream_char(self, ch: str) -> list[str]:
        if self._esc is not None:
            decoded = self._feed_escape(ch)
            return [c for c in decoded if c is not None]
        if ch == "\\":
            self._esc = "\\"
            return []
        if ch == '"':
            self._state = "AFTER"
            self._done = True
            return []
        return [ch]

    def _feed_escape(self, ch: str) -> list[str]:
        """转义处理：返回需发出的解码字符（流式模式下）；跳过模式下返回空。"""
        esc = self._esc
        if esc == "\\":
            if ch == "u":
                self._esc = "u"
                self._esc_buf = []
                return []
            mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
            self._esc = None
            decoded = mapping.get(ch)
            return [decoded] if decoded else []
        if esc == "u":
            self._esc_buf.append(ch)
            if len(self._esc_buf) == 4:
                self._esc = None
                try:
                    return [chr(int("".join(self._esc_buf), 16))]
                except ValueError:
                    return []
            return []
        return []


# ---- 回调处理器：挂 on_llm_new_token -------------------------------------------


class ContentStreamHandler(BaseCallbackHandler):
    """增量提取结构化输出中的 content 并通过 send_delta 推送。

    仅当模型流式返回 name=AgentOutput 的 tool_call args 时才产生 delta；
    其他工具调用的 args 一律忽略。
    """

    def __init__(self, send_delta: Callable[[str], Awaitable[None]]) -> None:
        self._send_delta = send_delta
        self._extractor = _ContentFieldStream()
        self._active = False  # 当前流式片段是否属于 AgentOutput 工具调用

    async def on_llm_new_token(self, token: str, chunk=None, **kwargs) -> None:  # noqa: ANN001
        # chunk 是 ChatGenerationChunk，消息体在 .message 上（AIMessageChunk）
        message = getattr(chunk, "message", chunk)
        chunks = getattr(message, "tool_call_chunks", None) or []
        for tcc in chunks:
            name = tcc.get("name")
            args_frag = tcc.get("args") or ""
            if name is not None:
                # 新的工具调用声明：只有结构化输出工具才激活流式提取
                self._active = name == STRUCTURED_TOOL_NAME
            if not self._active or not args_frag:
                continue
            for delta in self._extractor.feed(args_frag):
                if delta:
                    await self._send_delta(delta)
