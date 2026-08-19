#!/usr/bin/env python3
from __future__ import annotations

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from godmod.max_bot import main
from godmod.max_api import MaxBotClient


def _client() -> MaxBotClient:
    token = os.environ.get("MAX_BOT_TOKEN") or os.environ.get("MAX_TOKEN") or ""
    if not token:
        raise RuntimeError("MAX_BOT_TOKEN is not set")
    return MaxBotClient(token, base_url=os.environ.get("MAX_API_BASE", "https://platform-api.max.ru"))


def _target_id(target: dict) -> str | int:
    if target.get("chat_id"):
        return f"chat:{target['chat_id']}"
    if target.get("user_id"):
        return f"user:{target['user_id']}"
    raise ValueError("target must contain chat_id or user_id")


def send_text(target: dict, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict:
    reply_markup = None
    if buttons:
        reply_markup = {"inline_keyboard": [[{"text": label, "callback_data": payload} for label, payload in row] for row in buttons]}
    return _client().send_message(_target_id(target), text, reply_markup=reply_markup)


def upload_and_send_file(target: dict, path: Path, caption: str) -> None:
    _client().send_document(_target_id(target), path, caption=caption)


if __name__ == "__main__":
    if "--poll" in sys.argv:
        sys.argv.remove("--poll")
    raise SystemExit(main())
