from __future__ import annotations

from contextlib import contextmanager
import json
import mimetypes
import socket
import uuid
from pathlib import Path
from urllib import error, parse, request


class TelegramApiError(RuntimeError):
    """Telegram Bot API transport or response error."""


class TelegramBotClient:
    def __init__(self, token: str, *, timeout: int = 60, prefer_ipv4: bool = True) -> None:
        self.token = token
        self.timeout = timeout
        self.prefer_ipv4 = prefer_ipv4
        self.base_url = f"https://api.telegram.org/bot{token}"

    def get_updates(self, *, offset: int | None = None, timeout: int = 30) -> list[dict]:
        payload: dict[str, object] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        data = self._post_json("getUpdates", payload)
        return data["result"]

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        data = self._post_json("sendMessage", payload)
        return data["result"]

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict:
        payload: dict[str, object] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        data = self._post_json("editMessageText", payload)
        return data["result"]

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        *,
        show_alert: bool = False,
    ) -> dict:
        payload: dict[str, object] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        data = self._post_json("answerCallbackQuery", payload)
        return data["result"]

    def set_my_commands(self, commands: list[dict[str, str]]) -> bool:
        payload = {"commands": json.dumps(commands, ensure_ascii=False)}
        data = self._post_json("setMyCommands", payload)
        return bool(data["result"])

    def delete_my_commands(self) -> bool:
        data = self._post_json("deleteMyCommands", {})
        return bool(data["result"])

    def set_chat_menu_button(self, menu_button: dict[str, str], *, chat_id: int | None = None) -> bool:
        payload: dict[str, object] = {"menu_button": json.dumps(menu_button, ensure_ascii=False)}
        if chat_id is not None:
            payload["chat_id"] = chat_id
        data = self._post_json("setChatMenuButton", payload)
        return bool(data["result"])

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        data = self._post_json("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        return bool(data["result"])

    def send_document(self, chat_id: int, file_path: str | Path, caption: str | None = None) -> dict:
        target = Path(file_path)
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption
        body, content_type = _build_multipart_body(fields, {"document": target})
        url = f"{self.base_url}/sendDocument"
        req = request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
        return self._open_request(req)["result"]

    def _post_json(self, method: str, payload: dict[str, object]) -> dict:
        encoded = parse.urlencode(payload).encode("utf-8")
        url = f"{self.base_url}/{method}"
        req = request.Request(url, data=encoded, method="POST")
        return self._open_request(req)

    def _open_request(self, req: request.Request) -> dict:
        try:
            with _prefer_ipv4_for_hosts(enabled=self.prefer_ipv4, hosts={"api.telegram.org"}):
                with request.urlopen(req, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise TelegramApiError(f"HTTP {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise TelegramApiError(f"Network error: {exc}") from exc

        if not data.get("ok"):
            raise TelegramApiError(str(data))
        return data


def _build_multipart_body(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = f"godmod-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, path in files.items():
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                path.read_bytes(),
                b"\r\n",
            ]
        )

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _prefer_ipv4_results(
    host: str | bytes | None,
    results: list[tuple[object, ...]],
    *,
    hosts: set[str],
) -> list[tuple[object, ...]]:
    if not isinstance(host, str) or host.casefold() not in hosts:
        return results
    ipv4_results = [item for item in results if item and item[0] == socket.AF_INET]
    return ipv4_results or results


@contextmanager
def _prefer_ipv4_for_hosts(*, enabled: bool, hosts: set[str]):
    if not enabled:
        yield
        return

    original_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        results = list(original_getaddrinfo(host, port, family, type, proto, flags))
        return _prefer_ipv4_results(host, results, hosts=hosts)

    socket.getaddrinfo = patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo
