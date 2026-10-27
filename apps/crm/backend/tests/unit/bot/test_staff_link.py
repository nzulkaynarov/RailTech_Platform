"""`/start staff_<код>`: команда сотрудника не перехватывает клиентский путь (W15-H6)."""

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.filters import CommandObject

from app.bot import staff_link
from app.domain import staff_telegram as rules
from app.services.staff_telegram_link import LinkOutcome

CODE = "A" * 16


def command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="start", args=args)


class FakeLinks:
    def __init__(self, outcome: LinkOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, int, str | None]] = []

    async def confirm(self, code: str, tg_user_id: int, username: str | None) -> LinkOutcome:
        self.calls.append((code, tg_user_id, username))
        return self.outcome


class FakeMessage:
    def __init__(self, language_code: str | None = None) -> None:
        self.from_user = SimpleNamespace(id=501, username="aziz", language_code=language_code)
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


@pytest.mark.parametrize("args", [None, "", "ref_site", "promo42", "staff_", "staff_short"])
def test_client_start_is_not_taken_by_the_staff_router(args: str | None) -> None:
    links: Any = FakeLinks(LinkOutcome("linked"))
    assert staff_link._is_staff_start(FakeMessage(), command(args), links) is False  # type: ignore[arg-type]


def test_staff_start_requires_the_service() -> None:
    assert staff_link._is_staff_start(FakeMessage(), command(f"staff_{CODE}")) is False  # type: ignore[arg-type]


def test_staff_start_is_recognised() -> None:
    links: Any = FakeLinks(LinkOutcome("linked"))
    found = staff_link._is_staff_start(FakeMessage(), command(f"staff_{CODE}"), links)  # type: ignore[arg-type]
    assert found == {"staff_code": CODE}


@pytest.mark.parametrize(
    ("outcome", "table", "language", "expected_language"),
    [
        (LinkOutcome("linked", "uz"), rules.LINKED, "ru", "uz"),
        (LinkOutcome("invalid"), rules.INVALID, "en", "en"),
        (LinkOutcome("invalid"), rules.INVALID, None, "ru"),
        (LinkOutcome("taken", "en"), rules.TAKEN, "ru", "en"),
    ],
)
async def test_reply_is_in_the_employee_language(
    outcome: LinkOutcome, table: dict[str, str], language: str | None, expected_language: str
) -> None:
    links = FakeLinks(outcome)
    message = FakeMessage(language)
    await staff_link.on_staff_start(message, CODE, links)  # type: ignore[arg-type]
    assert links.calls == [(CODE, 501, "aziz")]
    assert message.answers == [table[expected_language]]


def test_staff_router_is_included_ahead_of_the_client_routers() -> None:
    """Роутеры aiogram привязываются к одному диспетчеру, поэтому порядок проверяем по исходнику."""
    import inspect

    from app.bot.runtime import build_dispatcher

    source = inspect.getsource(build_dispatcher)
    staff = source.index("include_router(staff_link_router)")
    assert staff < source.index("include_router(client_handlers.router)")
    assert staff < source.index("include_router(handlers.router)")
