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
        self.markups: list[Any] = []

    async def answer(self, text: str, reply_markup: Any = None) -> None:
        self.answers.append(text)
        self.markups.append(reply_markup)


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
    await staff_link.on_staff_start(message, CODE, links)
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


class FakeChannel:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self.asked: list[int] = []

    async def invite_url(self, tg_user_id: int) -> str | None:
        self.asked.append(tg_user_id)
        return self.url


async def test_linking_sends_the_join_request_link_to_the_team_channel() -> None:
    message = FakeMessage("ru")
    channel: Any = FakeChannel("https://t.me/+join")
    await staff_link.on_staff_start(message, CODE, FakeLinks(LinkOutcome("linked", "ru")), channel)
    assert channel.asked == [501]
    assert message.answers == [rules.LINKED["ru"], rules.JOIN_CHANNEL["ru"]]
    button = message.markups[1].inline_keyboard[0][0]
    assert (button.text, button.url) == (rules.JOIN_BUTTON["ru"], "https://t.me/+join")


@pytest.mark.parametrize("outcome", [LinkOutcome("invalid"), LinkOutcome("taken")])
async def test_no_channel_link_unless_linked(outcome: LinkOutcome) -> None:
    channel: Any = FakeChannel("https://t.me/+join")
    message = FakeMessage()
    await staff_link.on_staff_start(message, CODE, FakeLinks(outcome), channel)
    assert channel.asked == []
    assert len(message.answers) == 1


async def test_no_second_message_without_a_link() -> None:
    message = FakeMessage()
    await staff_link.on_staff_start(
        message,
        CODE,
        FakeLinks(LinkOutcome("linked")),
        FakeChannel(None),  # type: ignore[arg-type]
    )
    assert len(message.answers) == 1
