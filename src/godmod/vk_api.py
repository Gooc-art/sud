from __future__ import annotations

import json
from http.client import IncompleteRead
import socket
import time
from typing import Any
from urllib import error, parse, request


class VkApiError(RuntimeError):
    """VK API transport or response error."""

    def __init__(self, message: str, *, code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class VkApiClient:
    def __init__(self, access_token: str, *, version: str = "5.199", timeout: int = 30) -> None:
        self.access_token = access_token
        self.version = version
        self.timeout = timeout
        self.base_url = "https://api.vk.com/method/"

    def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        payload = {
            "access_token": self.access_token,
            "v": self.version,
        }
        for key, value in (params or {}).items():
            if value is None:
                continue
            payload[key] = _serialize_param(value)

        url = f"{self.base_url}{method}?{parse.urlencode(payload)}"
        try:
            with request.urlopen(url, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise VkApiError(f"HTTP {exc.code}: {details}", code=exc.code) from exc
        except (TimeoutError, socket.timeout, IncompleteRead) as exc:
            raise VkApiError(f"Network error: {exc}", retryable=True) from exc
        except error.URLError as exc:
            raise VkApiError(f"Network error: {exc}", retryable=True) from exc

        if "error" in data:
            api_error = data["error"]
            message = api_error.get("error_msg", "VK API error")
            code = api_error.get("error_code")
            raise VkApiError(f"{message} (code={code})", code=code)
        if "response" not in data:
            raise VkApiError(f"Unexpected VK API response: {data}")
        return data["response"]

    def call_with_retry(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        retries: int = 2,
        retry_delay: float = 0.5,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return self.call(method, params)
            except VkApiError as exc:
                if attempt >= retries or (exc.code not in {6, 10, 29} and not exc.retryable):
                    raise
                time.sleep(retry_delay * (attempt + 1))
                attempt += 1


def _serialize_param(value: object) -> object:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    return value
