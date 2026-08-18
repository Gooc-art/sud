#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sud_export import COURTS


API_BASE = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ.get("MAX_TOKEN", "")
MAX_DAYS = int(os.environ.get("SUD_MAX_DAYS", "45"))
EXPORT_TIMEOUT_SECONDS = int(os.environ.get("SUD_EXPORT_TIMEOUT_SECONDS", str(4 * 60 * 60)))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("SUD_HTTP_TIMEOUT_SECONDS", "20"))
WEEKLY_CHAT_ID_FILE = Path(os.environ.get("SUD_WEEKLY_CHAT_ID_FILE", "~/.config/sud/weekly-chat-id")).expanduser()
ADMIN_USER_IDS = {int(user_id) for user_id in os.environ.get("SUD_ADMIN_USER_IDS", "").replace(",", " ").split()}
COMMERCE_PASSWORD = os.environ.get("SUD_COMMERCE_PASSWORD", "")


@dataclass
class Session:
    step: str = ""
    prev_step: str = ""
    date_from: date | None = None
    date_to: date | None = None
    court: str | None = None
    last_job: str | None = None
    menu_message_id: str | None = None


@dataclass
class Job:
    id: str
    target: dict
    date_from: date
    date_to: date
    court: str | None
    outdir: Path
    status: str = "queued"
    rows: int = 0
    error: str = ""
    started_at: float = field(default_factory=time.time)


sessions: dict[str, Session] = {}
jobs: dict[str, Job] = {}
job_queue: queue.Queue[Job] = queue.Queue()


def request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    if not TOKEN:
        raise RuntimeError("MAX_TOKEN is not set")
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": TOKEN}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=95) as resp:
        raw = resp.read()
    return json.loads(raw.decode() or "{}")


def multipart_upload(url: str, path: Path) -> dict:
    boundary = "----sud" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="data"; filename="{path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    data = head + path.read_bytes() + tail
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(data))},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode() or "{}")


def target_params(target: dict) -> dict:
    if target.get("chat_id"):
        return {"chat_id": target["chat_id"]}
    return {"user_id": target["user_id"]}


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [[{"type": "callback", "text": text, "payload": payload} for text, payload in row] for row in rows]
        },
    }


def message_id(response: dict) -> str | None:
    return (
        response.get("message_id")
        or response.get("mid")
        or (response.get("body") or {}).get("mid")
        or ((response.get("message") or {}).get("body") or {}).get("mid")
        or (response.get("message") or {}).get("message_id")
    )


def send_text(target: dict, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict:
    body = {"text": text[:4000]}
    if buttons:
        body["attachments"] = [keyboard(buttons)]
    response = request("POST", "/messages", target_params(target), body)
    time.sleep(0.55)
    return response


def show_menu(target: dict, text: str, buttons: list[list[tuple[str, str]]]) -> None:
    sess = sessions.setdefault(session_key(target), Session())
    body = {"text": text[:4000], "attachments": [keyboard(buttons)]}
    if sess.menu_message_id:
        try:
            response = request("PUT", "/messages", {"message_id": sess.menu_message_id}, body)
            if response.get("success") is False:
                raise RuntimeError(response.get("message") or "menu edit failed")
            time.sleep(0.55)
            return
        except Exception:
            sess.menu_message_id = None
    sess.menu_message_id = message_id(send_text(target, text, buttons))


def answer_callback(callback_id: str, text: str = "") -> None:
    if callback_id:
        request("POST", "/answers", {"callback_id": callback_id}, {"notification": text or "Принято"})


def ack_callback(callback_id: str) -> None:
    def run() -> None:
        try:
            answer_callback(callback_id, "Принято")
        except Exception as exc:
            print(f"callback answer error: {exc}", file=sys.stderr)

    if callback_id:
        threading.Thread(target=run, daemon=True).start()


def upload_and_send_file(target: dict, path: Path, caption: str) -> None:
    upload = request("POST", "/uploads", {"type": "file"})
    payload = multipart_upload(upload["url"], path)
    body = {"text": caption, "attachments": [{"type": "file", "payload": payload}]}
    for delay in (1, 2, 4):
        time.sleep(delay)
        try:
            request("POST", "/messages", target_params(target), body)
            time.sleep(0.55)
            return
        except Exception:
            if delay == 4:
                raise


def main_buttons() -> list[list[tuple[str, str]]]:
    return [[("📊 Выгрузка за месяц", "month")], [("💼 Выгрузка по коммерции", "commerce")], [("📅 Выбрать период", "period"), ("📌 Статус выгрузки", "status")], [("❌ Отмена", "cancel")]]


def nav_buttons(back: str = "main") -> list[tuple[str, str]]:
    return [("⬅️ Назад", back), ("🏠 Главное меню", "main")]


def period_buttons() -> list[list[tuple[str, str]]]:
    return [[("📆 Текущая неделя", "period_current"), ("📊 Прошлая неделя", "week")], [("✏️ Свой период", "period_custom")], nav_buttons()]


def court_buttons(prefix: str) -> list[list[tuple[str, str]]]:
    rows = [[("🏛 Все суды", f"{prefix}:all")]]
    rows += [[(name.replace(" городской суд", ""), f"{prefix}:{host}")] for host, name in COURTS.items()]
    rows.append(nav_buttons("period"))
    return rows


def confirm_buttons() -> list[list[tuple[str, str]]]:
    return [[("✅ Запустить выгрузку", "run_confirm")], [("📅 Изменить период", "period"), ("🏛 Изменить суд", "choose_court")], [("🏠 Главное меню", "main")]]


def last_full_week(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    return start, start + timedelta(days=6)


def last_full_month(today: date | None = None) -> tuple[date, date]:
    first_this_month = (today or date.today()).replace(day=1)
    end = first_this_month - timedelta(days=1)
    return end.replace(day=1), end


def current_week(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def parse_ru_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def session_key(target: dict) -> str:
    return str(target.get("chat_id") or target["user_id"])


def is_admin(target: dict) -> bool:
    user_id = target.get("user_id")
    return not ADMIN_USER_IDS or (user_id is not None and int(user_id) in ADMIN_USER_IDS)


def rows_count(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    with csv_path.open(encoding="utf-8-sig", errors="replace") as f:
        return max(0, sum(1 for _ in f) - 1)


def start_job(target: dict, start: date, end: date, court: str | None) -> Job:
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"Период слишком большой. Максимум: {MAX_DAYS} дней.")
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    outdir = Path("output") / "bot" / job_id
    job = Job(job_id, target, start, end, court, outdir)
    jobs[job_id] = job
    sessions.setdefault(session_key(target), Session()).last_job = job_id
    job_queue.put(job)
    return job


def court_name(host: str | None) -> str:
    return COURTS.get(host, "Все суды ЯНАО") if host else "Все суды ЯНАО"


def show_confirm(target: dict, sess: Session) -> None:
    show_menu(
        target,
        f"Проверьте параметры:\nПериод: {sess.date_from:%d.%m.%Y}-{sess.date_to:%d.%m.%Y}\nСуд: {court_name(sess.court)}",
        confirm_buttons(),
    )


def save_weekly_chat(target: dict) -> bool:
    chat_id = target.get("chat_id")
    if not chat_id:
        return False
    WEEKLY_CHAT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_CHAT_ID_FILE.write_text(str(chat_id), encoding="utf-8")
    return True


def done_message(job: Job) -> str:
    text = f"Готово. Суд: {court_name(job.court)}. Найдено записей: {job.rows}."
    if job.rows == 0 and job.date_to > date.today():
        text += " Часть периода в будущем, расписание могло быть еще не опубликовано."
    return text + " Отправляю файлы."


def worker() -> None:
    while True:
        job = job_queue.get()
        job.status = "running"
        try:
            cmd = [
                sys.executable,
                "sud_export.py",
                "--from",
                job.date_from.isoformat(),
                "--to",
                job.date_to.isoformat(),
                "--outdir",
                str(job.outdir),
                "--timeout",
                str(HTTP_TIMEOUT_SECONDS),
                "--sort-by-lawyer",
            ]
            if job.court:
                cmd += ["--court", job.court]
            result = subprocess.run(cmd, text=True, capture_output=True, timeout=EXPORT_TIMEOUT_SECONDS)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout).strip())
            match = re.search(r"rows=(\d+)", result.stdout)
            job.rows = int(match.group(1)) if match else rows_count(job.outdir / "report.csv")
            job.status = "done"
            show_menu(job.target, done_message(job), [[("Новая выгрузка", "period")], [("Главное меню", "main")]])
            for name, caption in (
                ("report.xlsx", "Excel-отчет"),
                ("report.pdf", "PDF-версия"),
                ("report.html", "HTML-отчет"),
                ("report.csv", "CSV-данные"),
            ):
                path = job.outdir / name
                if path.exists():
                    upload_and_send_file(job.target, path, caption)
            log = job.outdir / "run_log.csv"
            if log.exists() and log.stat().st_size > 64:
                upload_and_send_file(job.target, log, "Лог выполнения")
            show_menu(job.target, "Можно запускать новую выгрузку.", main_buttons())
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            show_menu(job.target, f"Выгрузка не завершилась: {job.error[:1000]}", [[("Статус выгрузки", "status")], [("Главное меню", "main")]])
            log = job.outdir / "run_log.csv"
            if log.exists():
                upload_and_send_file(job.target, log, "Лог выполнения")
        finally:
            job_queue.task_done()


def extract_event(update: dict) -> tuple[dict, str, str, str]:
    event = update.get("message_callback") or {}
    callback = update.get("callback") or event.get("callback") or event
    message = update.get("message") or event.get("message") or update.get("message_created", {}).get("message") or {}
    body = message.get("body") or {}
    text = body.get("text") or message.get("text") or ("/start" if update.get("update_type") == "bot_started" else "")
    payload = callback.get("payload") or ""
    callback_id = callback.get("callback_id") or ""
    chat = message.get("chat") or message.get("recipient") or callback.get("chat") or {}
    user = callback.get("user") or update.get("user") or message.get("sender") or message.get("user") or {}
    target = {}
    chat_id = chat.get("chat_id") or message.get("chat_id") or callback.get("chat_id") or update.get("chat_id")
    user_id = user.get("user_id") or message.get("user_id") or callback.get("user_id") or update.get("user_id")
    if chat_id:
        target["chat_id"] = chat_id
    if user_id:
        target["user_id"] = user_id
    return target, text.strip(), payload.strip(), callback_id


def handle(target: dict, text: str, payload: str = "", callback_id: str = "") -> None:
    if not target.get("user_id") and not target.get("chat_id"):
        return
    if not is_admin(target):
        send_text(target, "Нет доступа.")
        ack_callback(callback_id)
        return
    key = session_key(target)
    sess = sessions.setdefault(key, Session())
    action = payload or text

    if sess.step == "commerce_password" and payload and action not in {"main", "cancel"}:
        show_menu(target, "Введите пароль для выгрузки по коммерции.", [nav_buttons()])
        ack_callback(callback_id)
        return

    if action in {"/start", "start", "Старт", "main"}:
        sess.step = ""
        show_menu(target, "Бот делает выгрузку судебных дел ЯНАО в Excel/PDF/CSV.", main_buttons())
    elif action in {"/month", "month"}:
        sess.date_from, sess.date_to = last_full_month()
        sess.court = None
        sess.step = "month_court"
        show_menu(target, f"Период: {sess.date_from:%d.%m.%Y}-{sess.date_to:%d.%m.%Y}. Выберите суд.", court_buttons("court"))
    elif action in {"/week", "week"}:
        sess.date_from, sess.date_to = last_full_week()
        sess.court = None
        sess.step = "week_court"
        show_menu(target, f"Период: {sess.date_from:%d.%m.%Y}-{sess.date_to:%d.%m.%Y}. Выберите суд.", court_buttons("court"))
    elif action in {"/period", "period"}:
        sess.step = "period"
        show_menu(target, "Выберите период выгрузки.", period_buttons())
    elif action == "period_current":
        sess.date_from, sess.date_to = current_week()
        sess.court = None
        sess.step = "period_court"
        show_menu(target, f"Период: {sess.date_from:%d.%m.%Y}-{sess.date_to:%d.%m.%Y}. Выберите суд.", court_buttons("court"))
    elif action == "period_custom":
        sess.court = None
        sess.step = "from"
        show_menu(target, "Введите дату начала в формате ДД.ММ.ГГГГ.", [nav_buttons("period")])
    elif action == "commerce":
        if not COMMERCE_PASSWORD:
            show_menu(target, "Пароль коммерции не настроен.", main_buttons())
        else:
            sess.step = "commerce_password"
            show_menu(target, "Введите пароль для выгрузки по коммерции.", [nav_buttons()])
    elif action == "status" or action == "/status":
        job = jobs.get(sess.last_job or "")
        if not job:
            show_menu(target, "Задач пока нет.", [[("🔄 Обновить статус", "status")], [("🏠 Главное меню", "main")]])
        else:
            show_menu(target, f"Последняя задача: {job.status}. Суд: {court_name(job.court)}. Записей: {job.rows}. Ошибка: {job.error or '-'}", [[("🔄 Обновить статус", "status")], [("🏠 Главное меню", "main")]])
    elif action == "/weekly_here":
        if save_weekly_chat(target):
            show_menu(target, "Этот чат сохранен для еженедельных уведомлений по ФНС.", main_buttons())
        else:
            show_menu(target, "Команду нужно отправить в групповом чате.", main_buttons())
    elif action in {"cancel", "/cancel"}:
        sess.step = ""
        show_menu(target, "Отменено.", main_buttons())
    elif action == "choose_court":
        sess.step = "period_court"
        show_menu(target, "Выберите суд.", court_buttons("court"))
    elif action.startswith("court:"):
        if not sess.date_from or not sess.date_to:
            sess.step = "period"
            show_menu(target, "Сначала выберите период выгрузки.", period_buttons())
        else:
            court = action.split(":", 1)[1]
            sess.court = None if court == "all" else court
            sess.step = "confirm"
            show_confirm(target, sess)
    elif action == "run_confirm":
        if not sess.date_from or not sess.date_to:
            sess.step = "period"
            show_menu(target, "Сначала выберите период выгрузки.", period_buttons())
        else:
            try:
                job = start_job(target, sess.date_from, sess.date_to, sess.court)
                sess.step = "running"
                show_menu(target, f"Принял, собираю отчет за {job.date_from:%d.%m.%Y}-{job.date_to:%d.%m.%Y}. Суд: {court_name(job.court)}. Это может занять несколько минут.", [[("📌 Статус выгрузки", "status")], [("🏠 Главное меню", "main")]])
            except ValueError as exc:
                show_menu(target, str(exc), main_buttons())
    elif sess.step == "from":
        parsed = parse_ru_date(text)
        if not parsed:
            show_menu(target, "Не понял дату. Введите в формате ДД.ММ.ГГГГ, например 29.07.2026.", [nav_buttons("period")])
            return
        sess.date_from = parsed
        sess.step = "to"
        show_menu(target, "Введите дату окончания в формате ДД.ММ.ГГГГ.", [nav_buttons("period")])
    elif sess.step == "to":
        parsed = parse_ru_date(text)
        if not parsed:
            show_menu(target, "Не понял дату. Введите в формате ДД.ММ.ГГГГ, например 29.07.2026.", [nav_buttons("period")])
            return
        if sess.date_from and parsed < sess.date_from:
            show_menu(target, "Дата окончания не может быть раньше даты начала.", [nav_buttons("period")])
            return
        sess.date_to = parsed
        sess.step = "period_court"
        show_menu(target, "Выберите суд.", court_buttons("court"))
    elif sess.step == "commerce_password":
        if text == COMMERCE_PASSWORD:
            sess.step = "period"
            show_menu(target, "Выберите период выгрузки по коммерции.", period_buttons())
        else:
            show_menu(target, "Неверный пароль. Введите пароль еще раз.", [nav_buttons()])
    else:
        show_menu(target, "Выберите действие.", main_buttons())
    try:
        ack_callback(callback_id)
    except Exception as exc:
        print(f"callback answer error: {exc}", file=sys.stderr)


def poll() -> None:
    marker = None
    while True:
        params = {"limit": 20, "timeout": 30, "types": "bot_started,message_created,message_callback"}
        if marker is not None:
            params["marker"] = marker
        data = request("GET", "/updates", params)
        marker = data.get("marker", marker)
        for update in data.get("updates") or []:
            try:
                handle(*extract_event(update))
            except Exception as exc:
                print(f"update error: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", action="store_true", help="run MAX long polling bot")
    args = parser.parse_args()
    if not args.poll:
        parser.error("use --poll")
    threading.Thread(target=worker, daemon=True).start()
    poll()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
