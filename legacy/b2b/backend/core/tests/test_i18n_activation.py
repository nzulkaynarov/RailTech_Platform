"""L0 — активация языка (spec-bilingual-ru-en-2026-08-02).

Два канала, и тесты держат их раздельно:

* язык ЗАПРОСА — `Accept-Language` от SPA активируется `LocaleMiddleware`; проверяем на
  строках, которые Django/DRF переводят своими каталогами (наш собственный каталог может
  быть неполон, а вот встроенные — полны и стабильны);
* язык ПОЛУЧАТЕЛЯ — `resolve_user_language`/`user_language` для писем и фоновых задач,
  где запроса нет вообще (канон Odoo `partner.lang` / Stripe `preferred_locales`).
"""

import pytest
from django.conf import settings
from django.utils import translation
from rest_framework.test import APIClient

from accounts.models import CustomUser
from core.i18n import resolve_user_language, supported_languages, user_language


def test_locale_middleware_is_installed():
    """Без него весь слой gettext инертен — именно это и было до L0."""
    assert "django.middleware.locale.LocaleMiddleware" in settings.MIDDLEWARE
    # Канонная позиция Django: после сессий, до CommonMiddleware.
    index = settings.MIDDLEWARE.index("django.middleware.locale.LocaleMiddleware")
    assert index > settings.MIDDLEWARE.index("django.contrib.sessions.middleware.SessionMiddleware")
    assert index < settings.MIDDLEWARE.index("django.middleware.common.CommonMiddleware")


def test_supported_languages_come_from_settings():
    assert supported_languages() == {"ru", "en"}
    assert settings.LANGUAGE_CODE == "ru"


@pytest.mark.django_db
def test_request_language_follows_accept_language_header():
    """Ответ API говорит на языке запроса. Проверяем на DRF-строке (её каталоги полные)."""
    client = APIClient()

    ru = client.post("/api/v1/auth/token/", {}, format="json", HTTP_ACCEPT_LANGUAGE="ru")
    en = client.post("/api/v1/auth/token/", {}, format="json", HTTP_ACCEPT_LANGUAGE="en")

    assert ru.status_code == en.status_code == 400
    ru_text = str(ru.json())
    en_text = str(en.json())
    assert "обязательное" in ru_text.lower(), ru_text
    assert "required" in en_text.lower(), en_text
    assert ru_text != en_text, "язык запроса не влияет на ответ — LocaleMiddleware не работает"


@pytest.mark.django_db
def test_unknown_language_falls_back_to_platform_default():
    client = APIClient()
    resp = client.post("/api/v1/auth/token/", {}, format="json", HTTP_ACCEPT_LANGUAGE="fr")
    assert "обязательное" in str(resp.json()).lower(), "неизвестный язык обязан падать в ru"


@pytest.mark.django_db
def test_recipient_language_resolves_from_user_preferences():
    """Язык ПОЛУЧАТЕЛЯ — из его собственных настроек, а не из того, кто нажал кнопку."""
    en_user = CustomUser.objects.create_user(
        email="en@i18n.test", username="en@i18n.test", password="x", preferences={"language": "en"}
    )
    ru_user = CustomUser.objects.create_user(
        email="ru@i18n.test", username="ru@i18n.test", password="x", preferences={"language": "ru"}
    )
    blank_user = CustomUser.objects.create_user(email="b@i18n.test", username="b@i18n.test", password="x")

    assert resolve_user_language(en_user) == "en"
    assert resolve_user_language(ru_user) == "ru"
    assert resolve_user_language(blank_user) == "ru", "нет настройки → язык платформы"


@pytest.mark.django_db
def test_recipient_language_never_raises_on_broken_preferences():
    """Письмо не должно падать из-за мусора в настройках."""
    for junk in ({"language": "klingon"}, {"language": 42}, {}, None, "not-a-dict"):
        user = CustomUser(email="x@i18n.test", preferences=junk)
        assert resolve_user_language(user) == "ru"


@pytest.mark.django_db
def test_user_language_context_activates_and_restores():
    user = CustomUser.objects.create_user(
        email="ctx@i18n.test", username="ctx@i18n.test", password="x", preferences={"language": "en"}
    )
    with translation.override("ru"):
        with user_language(user):
            assert translation.get_language() == "en"
        assert translation.get_language() == "ru", "язык обязан восстановиться после блока"


def test_project_catalog_translates_its_own_strings():
    """Собственный каталог (locale/en) заполнен и скомпилирован — не только Django/DRF.

    Проверяем доменные термины, которые обязаны совпадать со словарём SPA: расхождение
    здесь означало бы, что API и интерфейс называют одну вещь разными словами.
    """
    from django.utils.translation import gettext

    with translation.override("en"):
        assert gettext("Компания") == "Company"
        assert gettext("Сделка") == "Deal"
        assert gettext("Дата создания") == "Created at"
    with translation.override("ru"):
        assert gettext("Компания") == "Компания", "русский — источник, перевода не требует"


def test_catalog_placeholders_are_intact():
    """Потерянный %(name)s в переводе — это падение интерполяции в проде, а не косметика."""
    import re
    from pathlib import Path

    po = Path(settings.BASE_DIR / "locale" / "en" / "LC_MESSAGES" / "django.po").read_text(encoding="utf-8")
    pairs = re.findall(r'msgid ((?:"[^"]*"\n)+)msgstr ((?:"[^"]*"\n)+)', po)
    placeholder = re.compile(r"%\([a-zA-Z_]+\)[sd]|%[sd]|\{[a-zA-Z_]+\}")

    def value(raw):
        return "".join(re.findall(r'"([^"]*)"', raw))

    mismatched = [
        value(src)
        for src, dst in pairs
        if value(src)
        and value(dst)
        and sorted(placeholder.findall(value(src))) != sorted(placeholder.findall(value(dst)))
    ]
    assert not mismatched, f"перевод потерял плейсхолдеры: {mismatched[:3]}"


def test_catalog_has_no_fuzzy_or_empty_entries():
    """Fuzzy-запись — это ДОГАДКА gettext, которую Django при компиляции игнорирует.

    Ловушка волны L2: `makemessages` подставил новым строкам писем переводы похожих
    старых («Здравствуйте!» → «Valid until») и пометил их fuzzy. Каталог выглядел
    заполненным, а письмо приходило по-русски. Пустая запись — то же самое, только явно.
    """
    from pathlib import Path

    po = Path(settings.BASE_DIR / "locale" / "en" / "LC_MESSAGES" / "django.po").read_text(encoding="utf-8")
    # Первый fuzzy — служебный заголовок каталога (msgid ""), он таким и рождается.
    body = po.split("\n\n", 1)[1] if "\n\n" in po else po
    # Считаем подстрокой, а не целой строкой: gettext пишет флаги списком —
    # «#, fuzzy, python-format». Волна M1 потеряла на этом 8 записей номеров и дат
    # документов (в английском PDF стояло «Договор № …»), потому что ручная проверка
    # сравнивала строку целиком.
    fuzzy_count = body.count("#, fuzzy")
    assert fuzzy_count == 0, f"{fuzzy_count} fuzzy-записей: Django их не применит, строка останется русской"

    lines = body.split("\n")
    untranslated = []
    for index, line in enumerate(lines):
        if line != 'msgstr ""':
            continue
        continuation = lines[index + 1] if index + 1 < len(lines) else ""
        if continuation.startswith('"'):
            continue  # перевод многострочный, а не пустой
        source = lines[index - 1] if index else ""
        if source.startswith("msgid "):
            untranslated.append(source.removeprefix("msgid ").strip('"'))
    assert not untranslated, f"{len(untranslated)} строк без перевода, напр.: {untranslated[:3]}"
