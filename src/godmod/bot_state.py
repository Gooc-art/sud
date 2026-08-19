from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


ChatId = int | str
UserId = int | str
MessageId = int | str


WizardStep = Literal[
    "select_city",
    "select_service",
    "manual_service_input",
    "select_period",
    "select_mode",
    "confirm",
    "running",
    "done",
]


@dataclass(slots=True)
class WizardState:
    chat_id: ChatId
    user_id: UserId
    step: WizardStep = "select_city"
    city: str | None = None
    service_category: str | None = None
    services: list[str] = field(default_factory=list)
    period_days: int | None = None
    report_mode: str | None = None
    top_n: int = 20
    wizard_message_id: MessageId | None = None
    transient_message_ids: list[MessageId] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)


WIZARD_STATES: dict[tuple[ChatId, UserId], WizardState] = {}


def wizard_state_key(chat_id: ChatId, user_id: UserId) -> tuple[ChatId, UserId]:
    return chat_id, user_id


def get_wizard_state(chat_id: ChatId, user_id: UserId) -> WizardState | None:
    return WIZARD_STATES.get(wizard_state_key(chat_id, user_id))


def ensure_wizard_state(
    chat_id: ChatId,
    user_id: UserId,
    *,
    default_top_n: int,
    wizard_message_id: MessageId | None = None,
) -> WizardState:
    key = wizard_state_key(chat_id, user_id)
    state = WIZARD_STATES.get(key)
    if state is None:
        state = WizardState(
            chat_id=chat_id,
            user_id=user_id,
            top_n=default_top_n,
            wizard_message_id=wizard_message_id,
        )
        WIZARD_STATES[key] = state
        return state
    if wizard_message_id is not None and state.wizard_message_id is None:
        state.wizard_message_id = wizard_message_id
    return state


def reset_wizard_state(state: WizardState) -> WizardState:
    state.step = "select_city"
    state.city = None
    state.service_category = None
    state.services = []
    state.period_days = None
    state.report_mode = None
    state.touch()
    return state


def clear_wizard_state(chat_id: ChatId, user_id: UserId) -> None:
    WIZARD_STATES.pop(wizard_state_key(chat_id, user_id), None)
