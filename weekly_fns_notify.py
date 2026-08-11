#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import max_bot
from sud_export import Row, is_tax_party


CHAT_ID_FILE = Path(os.environ.get("SUD_WEEKLY_CHAT_ID_FILE", "~/.config/sud/weekly-chat-id")).expanduser()


def next_week(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today - timedelta(days=today.weekday()) + timedelta(days=7)
    return start, start + timedelta(days=6)


def tax_rows(csv_path: Path) -> list[list[str]]:
    if not csv_path.exists():
        return []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    found = []
    for cells in rows[1:]:
        cells += [""] * 13
        row = Row(cells[2], cells[3], cells[4], cells[5], cells[6], cells[7], cells[8], cells[9], cells[10], cells[11], cells[12])
        if is_tax_party(row):
            found.append(cells)
    return found


def run_export(start: date, end: date, outdir: Path, timeout: int) -> None:
    cmd = [
        sys.executable,
        "sud_export.py",
        "--from",
        start.isoformat(),
        "--to",
        end.isoformat(),
        "--outdir",
        str(outdir),
        "--timeout",
        str(timeout),
        "--sort-by-lawyer",
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=int(os.environ.get("SUD_EXPORT_TIMEOUT_SECONDS", str(4 * 60 * 60))))
    if result.returncode and not (outdir / "report.csv").exists():
        raise RuntimeError((result.stderr or result.stdout).strip())
    print((result.stdout or result.stderr).strip())


def notify(chat_id: str, start: date, end: date, outdir: Path, count: int, force: bool = False) -> None:
    target = {"chat_id": chat_id}
    if count:
        text = f"ФНС найдена в судебных заседаниях на {start:%d.%m.%Y}-{end:%d.%m.%Y}: {count}. Отправляю Excel."
    else:
        text = f"Тестовый прогон ФНС на {start:%d.%m.%Y}-{end:%d.%m.%Y}: ФНС не найдена. Отправляю Excel для проверки доставки."
    max_bot.send_text(target, text)
    max_bot.upload_and_send_file(target, outdir / "report.xlsx", "Excel-отчет")


def weekly_chat_id() -> str:
    env_chat_id = os.environ.get("SUD_WEEKLY_CHAT_ID", "").strip()
    if env_chat_id:
        return env_chat_id
    if CHAT_ID_FILE.exists():
        return CHAT_ID_FILE.read_text(encoding="utf-8").strip()
    return ""


def weekly_chat_ids() -> list[str]:
    chat_ids = [os.environ.get("SUD_WEEKLY_CHAT_ID", "").strip()]
    if CHAT_ID_FILE.exists():
        chat_ids.append(CHAT_ID_FILE.read_text(encoding="utf-8").strip())
    return list(dict.fromkeys(chat_id for chat_id in chat_ids if chat_id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="today override, YYYY-MM-DD")
    parser.add_argument("--outdir", help="output dir")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("SUD_HTTP_TIMEOUT_SECONDS", "20")))
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args(argv)

    today = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    start, end = next_week(today)
    outdir = Path(args.outdir or f"output/weekly-fns/{start.isoformat()}")

    if not args.skip_export:
        run_export(start, end, outdir, args.timeout)
    found = tax_rows(outdir / "report.csv")
    print(f"tax_rows={len(found)} xlsx={outdir / 'report.xlsx'}")

    chat_ids = weekly_chat_ids()
    if (found or args.force_send) and not args.no_send:
        if not chat_ids:
            raise RuntimeError("SUD_WEEKLY_CHAT_ID is not set")
        for chat_id in chat_ids:
            if not re.fullmatch(r"-?\d+", chat_id):
                raise RuntimeError("SUD_WEEKLY_CHAT_ID is not set")
            notify(chat_id, start, end, outdir, len(found), args.force_send)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
