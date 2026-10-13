"""Резолв языка (волна L0, `spec-bilingual-ru-en-2026-08-02.md`).

Два РАЗНЫХ канала, и путать их нельзя (канон Odoo `partner.lang` / Stripe
`preferred_locales`):

* **язык запроса** — чем отвечает API прямо сейчас. Ставит `LocaleMiddleware` по
  заголовку `Accept-Language`, который SPA шлёт из `i18n.language`. Ничего
  дополнительно писать не нужно — Django уже умеет.
* **язык ПОЛУЧАТЕЛЯ** — на каком языке человек получит письмо или уведомление,
  которые рождаются в Celery, где никакого запроса нет. Берётся из его собственных
  настроек: `resolve_user_language(user)` + `user_language(user)`.

Почему не «язык того, кто нажал кнопку»: счёт выставляет продавец, а письмо читает
покупатель. Язык отправителя к языку адресата отношения не имеет.
"""

from contextlib import contextmanager

from django.conf import settings
from django.utils import translation


def supported_languages() -> set:
    """Коды языков, объявленных в settings.LANGUAGES (единственный источник)."""
    return {code for code, _label in settings.LANGUAGES}


def resolve_user_language(user) -> str:
    """Язык ЭТОГО пользователя: его настройка, иначе язык платформы по умолчанию.

    Никогда не падает: анонимный/None-пользователь, отсутствующие или битые
    `preferences`, незнакомый код — всё сводится к `settings.LANGUAGE_CODE`.
    """
    default = settings.LANGUAGE_CODE
    preferences = getattr(user, "preferences", None)
    if not isinstance(preferences, dict):
        return default
    code = preferences.get("language")
    if not isinstance(code, str):
        return default
    code = code.strip().lower()
    return code if code in supported_languages() else default


@contextmanager
def user_language(user):
    """Выполнить блок на языке ПОЛУЧАТЕЛЯ (письма, уведомления, фоновые задачи).

    Обёртка над `translation.override`, чтобы вызывающему коду не приходилось
    самому помнить про резолв и про восстановление прежнего языка.
    """
    with translation.override(resolve_user_language(user)):
        yield
