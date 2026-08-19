from __future__ import annotations

from dataclasses import dataclass

from .request_options import parse_period_value


@dataclass(slots=True)
class ParsedCommand:
    name: str
    args: dict[str, object]


BOT_COMMANDS = [
    {"command": "start", "description": "Открыть стартовое меню"},
    {"command": "cities", "description": "Выбрать город ЯНАО"},
    {"command": "help", "description": "Показать справку"},
    {"command": "cancel", "description": "Сбросить текущий выбор"},
    {"command": "sample", "description": "Собрать тестовый Excel"},
    {"command": "report", "description": "Собрать отчёт вручную"},
    {"command": "markupplan", "description": "Собрать JSON-план разметки validation-dataset"},
    {"command": "health", "description": "Собрать health-снимок бота и последних артефактов"},
    {"command": "dailyreport", "description": "Собрать ежедневную сводку по выгрузкам"},
    {"command": "lastreport", "description": "Повторно отправить последнюю выгрузку из output"},
]


START_TEXT = """Выберите город кнопкой ниже и пройдите шаги отчёта.

Сценарий простой:
город → услуги → период → режим → подтверждение.

Можно выбрать кнопку «Все сферы деятельности» или ввести услуги вручную.
Отчёт приходит в `xlsx` и дополнительном табличном `pdf`.
"""


HELP_TEXT = """Как пользоваться ботом:

1. Нажмите «Старт» или отправьте `/start`.
2. Выберите город ЯНАО.
3. Выберите услугу или кнопку «Все сферы деятельности».
4. Выберите период, включая `За всё время`.
5. Подтвердите запуск и дождитесь выгрузки.

Ручные команды:
/start
/help
/cities
/cancel
/report <города> | <услуги> | <период_дней> | <top_n> | <режим?>

Примеры:
/report Салехард,Новый Уренгой | маникюр,ремонт | 60 | 20
/report Салехард | все сферы деятельности | 0 | 20
/report Салехард | маникюр | 60 | 20 | official
"""


def parse_command(text: str) -> ParsedCommand | None:
    message = text.strip()
    plain_message = message.casefold()
    if plain_message in {"старт", "start"}:
        return ParsedCommand(name="start", args={})
    if plain_message in {"города", "cities"}:
        return ParsedCommand(name="cities", args={})
    if plain_message in {"помощь", "help"}:
        return ParsedCommand(name="help", args={})
    if plain_message in {"сброс", "отмена", "cancel"}:
        return ParsedCommand(name="cancel", args={})
    if not message.startswith("/"):
        return None

    command, _, rest = message.partition(" ")
    command = command.casefold()
    command_name = _command_name(command)
    if command_name is None:
        return ParsedCommand(name="unknown", args={"raw_command": command})
    if command_name in {"start", "help", "cities", "cancel", "health", "dailyreport", "lastreport"}:
        return ParsedCommand(name=command_name, args={})
    if command_name == "access":
        code = rest.strip()
        if not code:
            raise ValueError("Нужен формат: /access <код>")
        return ParsedCommand(name="access", args={"code": code})
    if command_name == "sample":
        return ParsedCommand(name="sample", args={})
    if command_name == "report":
        cities, services, period_days, top_n, report_mode = _parse_report_args(rest)
        return ParsedCommand(
            name="report",
            args={
                "cities": cities,
                "services": services,
                "period_days": period_days,
                "top_n": top_n,
                "report_mode": report_mode,
            },
        )
    if command_name == "markupplan":
        group_by, batch_size, max_batches = _parse_markup_plan_args(rest)
        return ParsedCommand(
            name="markupplan",
            args={
                "group_by": group_by,
                "batch_size": batch_size,
                "max_batches": max_batches,
            },
        )
    return ParsedCommand(name="unknown", args={"raw_command": command})


def _command_name(command: str) -> str | None:
    if not command.startswith("/"):
        return None
    raw_name = command[1:]
    command_name, _, mention = raw_name.partition("@")
    if not command_name:
        return None
    if mention and not mention.replace("_", "").isalnum():
        return None
    return command_name


def _parse_report_args(raw_args: str) -> tuple[list[str], list[str], int, int, str]:
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) not in {4, 5}:
        raise ValueError("Нужен формат: /report <города> | <услуги> | <период_дней> | <top_n> | <режим?>")

    cities = _split_csv(parts[0])
    services = _split_csv(parts[1])
    if not cities or not services:
        raise ValueError("Нужно указать хотя бы один город и одну услугу.")

    period_days = parse_period_value(parts[2])
    top_n = int(parts[3])
    if top_n <= 0:
        raise ValueError("top_n должен быть больше нуля.")
    report_mode = _parse_report_mode(parts[4]) if len(parts) == 5 else "all"
    return cities, services, period_days, top_n, report_mode


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_report_mode(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"all", "все", "все исполнители"}:
        return "all"
    if normalized in {"official", "official_only", "только официальные", "официальные"}:
        return "official_only"
    raise ValueError("Режим должен быть all или official.")


def _parse_markup_plan_args(raw_args: str) -> tuple[str, int, int]:
    stripped = raw_args.strip()
    if not stripped:
        return "city", 10, 0
    parts = [part.strip() for part in raw_args.split("|")]
    if len(parts) > 3:
        raise ValueError("Нужен формат: /markupplan <group_by?> | <batch_size?> | <max_batches?>")

    group_by = _parse_markup_group(parts[0]) if parts and parts[0] else "city"
    batch_size = int(parts[1]) if len(parts) >= 2 and parts[1] else 10
    max_batches = int(parts[2]) if len(parts) >= 3 and parts[2] else 0
    if batch_size <= 0:
        raise ValueError("batch_size должен быть больше нуля.")
    if max_batches < 0:
        raise ValueError("max_batches не может быть отрицательным.")
    return group_by, batch_size, max_batches


def _parse_markup_group(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"city", "город", "города"}:
        return "city"
    if normalized in {"service", "услуга", "услуги"}:
        return "service"
    if normalized in {"none", "all", "общая", "общая очередь"}:
        return "none"
    raise ValueError("group_by должен быть city, service или none.")
