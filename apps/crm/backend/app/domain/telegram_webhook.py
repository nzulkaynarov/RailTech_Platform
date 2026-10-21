"""Адрес вебхука Telegram (FIX-66): Telegram принимает только https; пустой адрес — не «удалить».

Раньше при `TELEGRAM_MODE=webhook` и пустом `TELEGRAM_WEBHOOK_URL` CRM вызывала
`set_webhook("")` — для Bot API это `deleteWebhook`: бот молчал, а в журнале было «bot_started».
"""

from typing import Final, Literal
from urllib.parse import urlsplit

# Маршрут приёмника в `app/api/telegram.py` и `handle` в `infra/caddy/Caddyfile.prod`.
WEBHOOK_PATH: Final = "/telegram/webhook"

WebhookProblem = Literal["empty", "not_https"]


def webhook_url_problem(url: str) -> WebhookProblem | None:
    """Почему адрес не годится для `setWebhook`; `None` — годится."""
    value = url.strip()
    if not value:
        return "empty"
    try:
        parts = urlsplit(value)
    except ValueError:
        return "not_https"
    if parts.scheme.lower() != "https" or not parts.hostname:
        return "not_https"
    return None


PROBLEM_TEXT: Final[dict[str, str]] = {
    "empty": "TELEGRAM_WEBHOOK_URL пуст",
    "not_https": "TELEGRAM_WEBHOOK_URL должен быть https-адресом",
}
