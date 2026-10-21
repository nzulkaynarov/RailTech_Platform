"""Адрес вебхука Telegram (FIX-66): пустой или не-https адрес бота не запускает."""

import pytest

from app.domain.telegram_webhook import WEBHOOK_PATH, webhook_url_problem


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("http://crm.railtech.uz/telegram/webhook", "not_https"),
        ("ftp://crm.railtech.uz/telegram/webhook", "not_https"),
        ("crm.railtech.uz/telegram/webhook", "not_https"),
        ("https://", "not_https"),
        ("https:///telegram/webhook", "not_https"),
        ("https://crm.railtech.uz/telegram/webhook", None),
        ("HTTPS://CRM.RAILTECH.UZ/telegram/webhook", None),
    ],
)
def test_webhook_url_problem(url: str, problem: str | None) -> None:
    assert webhook_url_problem(url) == problem


def test_path_matches_the_receiver_route() -> None:
    from app.api.telegram import router

    assert any(getattr(r, "path", None) == WEBHOOK_PATH for r in router.routes)
