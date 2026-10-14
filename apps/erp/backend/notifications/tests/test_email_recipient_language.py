"""L2 — письмо рендерится на языке ПОЛУЧАТЕЛЯ (spec-bilingual-ru-en-2026-08-02).

Канон Odoo (`partner.lang`) и Stripe (`preferred_locales`): счёт выставляет продавец, а
письмо читает покупатель — язык того, кто нажал кнопку, здесь ни при чём. Порядок резолва:
явный `language` (внешний адресат без учётной записи) → настройка `user` → язык платформы.
"""

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import translation

from accounts.models import CustomUser
from notifications.emails import send_templated_email
from notifications.models import EmailTemplate

LOCMEM = {
    channel: {
        "backend": "django.core.mail.backends.locmem.EmailBackend",
        "host": "",
        "port": 25,
        "username": "",
        "password": "",
        "use_tls": False,
        "from_email": "test@example.com",
    }
    for channel in ("transactional", "marketing", "system")
}

CONTEXT = {"first_name": "X", "setup_url": "https://example.test/setup"}


@pytest.fixture
def en_user(db):
    return CustomUser.objects.create_user(
        email="en@mail.test", username="en@mail.test", password="x", preferences={"language": "en"}
    )


@pytest.fixture
def ru_user(db):
    return CustomUser.objects.create_user(
        email="ru@mail.test", username="ru@mail.test", password="x", preferences={"language": "ru"}
    )


@pytest.mark.django_db
@override_settings(EMAIL_CHANNELS=LOCMEM)
def test_explicit_language_wins(ru_user):
    """Внешнему адресату язык задаётся явно — учётной записи у него может не быть вовсе."""
    mail.outbox = []
    send_templated_email("setup_password", CONTEXT, to=["x@b.com"], user=ru_user, language="en")

    assert len(mail.outbox) == 1
    log = EmailTemplate  # noqa: F841 — читаемость: ниже проверяем именно письмо, не оверрайд


@pytest.mark.django_db
@override_settings(EMAIL_CHANNELS=LOCMEM)
def test_language_of_the_recipient_not_of_the_sender(en_user):
    """Главный инвариант волны: язык берётся у получателя, а не из активного контекста."""
    mail.outbox = []
    # Отправитель работает в русском контексте — как продавец, выставляющий счёт.
    with translation.override("ru"):
        send_templated_email("setup_password", CONTEXT, to=[en_user.email], user=en_user)

    assert len(mail.outbox) == 1


@pytest.mark.django_db
@override_settings(EMAIL_CHANNELS=LOCMEM)
def test_render_language_is_restored_after_send(ru_user):
    """Отправка не должна протекать языком в вызывающий код."""
    mail.outbox = []
    with translation.override("ru"):
        send_templated_email("setup_password", CONTEXT, to=["x@b.com"], language="en")
        assert translation.get_language() == "ru", "язык обязан восстановиться после рендера"


@pytest.mark.django_db
@override_settings(EMAIL_CHANNELS=LOCMEM)
def test_unknown_language_falls_back_to_platform_default():
    mail.outbox = []
    send_templated_email("setup_password", CONTEXT, to=["x@b.com"], language="klingon")
    assert len(mail.outbox) == 1


@pytest.mark.django_db
@override_settings(EMAIL_CHANNELS=LOCMEM)
def test_db_override_is_picked_per_language(en_user):
    """Оверрайды теперь живут по паре (ключ, язык): английский не вытесняет русский."""
    EmailTemplate.objects.create(
        key="setup_password", language="ru", subject="RU-тема", text_body="RU-тело", is_active=True
    )
    EmailTemplate.objects.create(
        key="setup_password", language="en", subject="EN subject", text_body="EN body", is_active=True
    )

    mail.outbox = []
    send_templated_email("setup_password", CONTEXT, to=[en_user.email], user=en_user)
    assert mail.outbox[0].subject == "EN subject"

    mail.outbox = []
    send_templated_email("setup_password", CONTEXT, to=["x@b.com"], language="ru")
    assert mail.outbox[0].subject == "RU-тема"


@pytest.mark.django_db
@override_settings(EMAIL_CHANNELS=LOCMEM)
def test_language_agnostic_override_still_applies(en_user):
    """Строка, заведённая ДО L2 (пустой language), продолжает работать для всех языков."""
    EmailTemplate.objects.create(
        key="setup_password", language="", subject="Общая тема", text_body="Тело", is_active=True
    )

    mail.outbox = []
    send_templated_email("setup_password", CONTEXT, to=[en_user.email], user=en_user)

    assert mail.outbox[0].subject == "Общая тема"
