"""电商业务 API（18081）客户端：统一解包 ApiResponse{code,message,data}。

错误分层：
- 商业层失败（code!=0 / 404 / 409 等）→ CommerceError（ToolExecutor 归 BUSINESS）
- 网络层失败（超时/连接）→ httpx 异常直接抛出（ToolExecutor 归 SERVICE_CALL）
"""

from typing import Any

import httpx

from app.conf.config import settings


class CommerceError(Exception):
    """业务层失败，message 面向用户可读。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class CommerceClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url or settings.commerce_api_base_url,
            timeout=timeout or settings.commerce_timeout_seconds,
        )

    async def get_data(self, path: str) -> Any:
        return await self._request("GET", path)

    async def post_data(self, path: str, payload: dict) -> Any:
        return await self._request("POST", path, json=payload)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError:
            # 网络层异常原样上抛，由 ToolExecutor 统一归类 SERVICE_CALL
            raise
        if resp.status_code == 200:
            body = resp.json()
            if body.get("code", 0) != 0:
                raise CommerceError(body.get("message", "业务处理失败"))
            return body.get("data")
        # 非 200：尝试取业务错误信息（404/409 等）
        try:
            body = resp.json()
            message = body.get("message") or body.get("detail") or f"业务请求失败({resp.status_code})"
        except Exception:
            message = f"业务请求失败({resp.status_code})"
        raise CommerceError(message, status_code=resp.status_code)

    async def aclose(self) -> None:
        await self._client.aclose()


_commerce_client: CommerceClient | None = None


def get_commerce_client() -> CommerceClient:
    global _commerce_client
    if _commerce_client is None:
        _commerce_client = CommerceClient()
    return _commerce_client


async def close_commerce_client() -> None:
    global _commerce_client
    if _commerce_client is not None:
        await _commerce_client.aclose()
        _commerce_client = None
