from __future__ import annotations

import json
import mimetypes
import socket
import time
import uuid
from pathlib import Path
from urllib import error, parse, request

from .telegram_api import TelegramApiError


class MaxApiError(TelegramApiError):
    """MAX Bot API transport or response error."""


_MAX_CITY_ICON = "📍"
_MAX_GENERIC_SERVICE_ICON = "🧩"
_MAX_SERVICE_ICON_BY_LABEL = {
    "все сферы деятельности": "🧭",
    "все услуги раздела": "✅",
    "красота и уход": "💅",
    "маникюр": "💅",
    "педикюр": "💅",
    "салон красоты": "✂️",
    "парикмахер": "✂️",
    "барбершоп": "💈",
    "брови": "👁️",
    "ресницы": "👁️",
    "косметолог": "🧴",
    "массаж": "💆",
    "общепит": "🍽️",
    "кафе": "🍽️",
    "кофейня": "☕",
    "ресторан": "🍽️",
    "пекарня": "🥐",
    "доставка еды": "🛵",
    "дом и ремонт": "🔧",
    "ремонт": "🔧",
    "электрик": "💡",
    "сантехник": "🚿",
    "клининг": "🧹",
    "химчистка": "🧺",
    "грузоперевозки": "🚚",
    "автоуслуги": "🚗",
    "автоэлектрик": "🔌",
    "автосервис": "🚗",
    "автомойка": "🚿",
    "шиномонтаж": "🛞",
    "здоровье и спорт": "🏥",
    "стоматология": "🦷",
    "фитнес": "🏋️",
    "образование и офис": "📚",
    "репетитор": "📚",
    "фотограф": "📷",
    "юрист": "⚖️",
    "бухгалтер": "🧾",
    "другие направления": _MAX_GENERIC_SERVICE_ICON,
}


class MaxBotClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: int = 60,
        base_url: str = "https://platform-api.max.ru",
        upload_ready_attempts: int = 4,
        upload_ready_delay_seconds: float = 1.0,
    ) -> None:
        self.token = token
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.upload_ready_attempts = upload_ready_attempts
        self.upload_ready_delay_seconds = upload_ready_delay_seconds

    def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int = 30,
        limit: int = 100,
        types: list[str] | None = None,
    ) -> dict:
        query: dict[str, object] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            query["marker"] = marker
        if types:
            query["types"] = ",".join(types)
        return self._request_json("GET", "updates", query=query)

    def clear_commands(self) -> dict:
        return self._request_json("PATCH", "me", json_body={"commands": []})

    def send_message(self, chat_id: int | str, text: str, reply_markup: dict | None = None) -> dict:
        return self._send_message_payload(chat_id, _new_message_body(text, reply_markup=reply_markup))

    def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int | str,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict:
        del chat_id
        data = self._request_json(
            "PUT",
            "messages",
            query={"message_id": str(message_id)},
            json_body=_new_message_body(text, reply_markup=reply_markup),
        )
        return _normalize_message_result(data)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        *,
        show_alert: bool = False,
    ) -> dict:
        del show_alert
        body = {"notification": text or ""}
        return self._request_json("POST", "answers", query={"callback_id": callback_query_id}, json_body=body)

    def delete_message(self, chat_id: int | str, message_id: int | str) -> bool:
        del chat_id
        data = self._request_json("DELETE", "messages", query={"message_id": str(message_id)})
        return bool(data.get("success", True))

    def send_document(self, chat_id: int | str, file_path: str | Path, caption: str | None = None) -> dict:
        payload = self.upload_file(file_path)
        body: dict[str, object] = {
            "text": caption or "",
            "attachments": [{"type": "file", "payload": payload}],
        }
        last_error: MaxApiError | None = None
        attempts = max(1, self.upload_ready_attempts)
        for attempt in range(attempts):
            try:
                return self._send_message_payload(chat_id, body)
            except MaxApiError as exc:
                last_error = exc
                if "attachment.not.ready" not in str(exc) or attempt == attempts - 1:
                    raise
                time.sleep(self.upload_ready_delay_seconds * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise MaxApiError("MAX document send failed.")

    def upload_file(self, file_path: str | Path) -> dict:
        target = Path(file_path)
        upload_meta = self._request_json("POST", "uploads", query={"type": "file"})
        upload_url = upload_meta.get("url")
        if not isinstance(upload_url, str) or not upload_url:
            raise MaxApiError(f"MAX upload URL is missing: {upload_meta}")

        body, content_type = _build_multipart_body({"data": target})
        req = request.Request(
            upload_url,
            data=body,
            headers={
                "Authorization": self.token,
                "Content-Type": content_type,
            },
            method="POST",
        )
        data = self._open_request(req, expect_json=True)
        if not isinstance(data, dict):
            raise MaxApiError(f"MAX upload response is not an object: {data!r}")
        return data

    def _send_message_payload(self, chat_id: int | str, body: dict[str, object]) -> dict:
        data = self._request_json("POST", "messages", query=_target_query(chat_id), json_body=body)
        return _normalize_message_result(data)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        data = None
        headers = {"Authorization": self.token}
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method=method)
        response_data = self._open_request(req, expect_json=True)
        if not isinstance(response_data, dict):
            raise MaxApiError(f"MAX response is not an object: {response_data!r}")
        if response_data.get("success") is False:
            raise MaxApiError(str(response_data))
        return response_data

    def _open_request(self, req: request.Request, *, expect_json: bool) -> object:
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise MaxApiError(f"HTTP {exc.code}: {details}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise MaxApiError(f"Network error: {exc}") from exc
        except error.URLError as exc:
            raise MaxApiError(f"Network error: {exc}") from exc

        if not expect_json:
            return raw
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MaxApiError(f"Invalid JSON response: {raw[:200]!r}") from exc


def _new_message_body(text: str, *, reply_markup: dict | None = None) -> dict[str, object]:
    body: dict[str, object] = {"text": text}
    attachments = _reply_markup_to_attachments(reply_markup)
    if attachments:
        body["attachments"] = attachments
    return body


def _reply_markup_to_attachments(reply_markup: dict | None) -> list[dict[str, object]]:
    if not reply_markup:
        return []
    buttons = _inline_keyboard_buttons(reply_markup)
    if not buttons:
        return []
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def _inline_keyboard_buttons(reply_markup: dict) -> list[list[dict[str, object]]]:
    rows = reply_markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return []

    result: list[list[dict[str, object]]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        converted_row: list[dict[str, object]] = []
        for button in row:
            if not isinstance(button, dict):
                continue
            text = str(button.get("text", "")).strip()
            if not text:
                continue
            if button.get("callback_data") is not None:
                payload = str(button["callback_data"])
                converted_row.append(
                    {
                        "type": "callback",
                        "text": _decorate_max_callback_button_text(text, payload),
                        "payload": payload,
                    }
                )
            elif button.get("url") is not None:
                converted_row.append({"type": "link", "text": text, "url": str(button["url"])})
            elif button.get("type") == "message":
                converted_row.append({"type": "message", "text": text})
            elif button.get("type") == "request_contact":
                converted_row.append({"type": "request_contact", "text": text})
        if converted_row:
            result.append(converted_row)
    return result


def _target_query(chat_id: int | str) -> dict[str, object]:
    if isinstance(chat_id, str):
        if chat_id.startswith("chat:"):
            return {"chat_id": chat_id.removeprefix("chat:")}
        if chat_id.startswith("user:"):
            return {"user_id": chat_id.removeprefix("user:")}
    return {"user_id": chat_id}


def _decorate_max_callback_button_text(text: str, payload: str) -> str:
    icon = _max_callback_button_icon(text, payload)
    if not icon or text.startswith(f"{icon} "):
        return text
    return f"{icon} {text}"


def _max_callback_button_icon(text: str, payload: str) -> str | None:
    if payload.startswith("wiz:v1:city:") or payload.startswith("city:"):
        return _MAX_CITY_ICON
    if payload.startswith("wiz:v1:service:") or payload.startswith("service:"):
        return _service_icon(text)
    if payload.startswith("wiz:v1:category:"):
        return _service_icon(text)
    return None


def _service_icon(text: str) -> str:
    return _MAX_SERVICE_ICON_BY_LABEL.get(_normalize_button_label(text), _MAX_GENERIC_SERVICE_ICON)


def _normalize_button_label(text: str) -> str:
    label = text.strip()
    if label.startswith("[") and label.endswith("]"):
        label = label[1:-1].strip()
    return " ".join(label.lower().split())


def _normalize_message_result(data: dict) -> dict:
    message = data.get("message") if isinstance(data.get("message"), dict) else data
    message_id = _find_message_id(message)
    if message_id is None:
        message_id = _find_message_id(data)
    result = {"raw": data}
    if message_id is not None:
        result["message_id"] = message_id
    return result


def _find_message_id(value: object) -> int | str | None:
    if not isinstance(value, dict):
        return None
    for key in ("message_id", "mid", "id"):
        candidate = value.get(key)
        if isinstance(candidate, int) or (isinstance(candidate, str) and candidate):
            return candidate
    body = value.get("body")
    if isinstance(body, dict):
        return _find_message_id(body)
    return None


def _build_multipart_body(files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = f"godmod-max-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
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
