"""Ссылка документа в Кабинет (ДК-1, ADR-0030): одна ссылка — один получатель, в базе только хеш токена.

Гость по ссылке видит один документ; любое действие требует кода, который уходит на адрес получателя (`recipient_email`
записан при выпуске ссылки и из запроса никогда не берётся). Ссылка имеет срок и отзывается отправителем. Журнал
`DocumentLinkEvent` — кто и когда открыл, запросил код, погасил его и что сделал.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class DocumentLinkKind(models.TextChoices):
    QUOTE = "quote", _("Коммерческое предложение")


class DocumentLink(models.Model):
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        verbose_name=_("SHA-256 токена ссылки"),
        help_text=_("Сырой токен есть только в письме получателя"),
    )
    kind = models.CharField(max_length=20, choices=DocumentLinkKind.choices, default=DocumentLinkKind.QUOTE)
    quote = models.ForeignKey(
        "sales.Quote",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_links",
        verbose_name=_("КП"),
    )
    contact = models.ForeignKey(
        "parties.Contact",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_links",
        verbose_name=_("Контакт-получатель"),
        help_text=_("Пусто — получателя нет среди контактов компании: документ виден, действий нет"),
    )
    recipient_email = models.EmailField(verbose_name=_("Адрес получателя"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True, verbose_name=_("Ссылка действует до"))
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Отозвана"))
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    first_opened_at = models.DateTimeField(null=True, blank=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    open_count = models.PositiveIntegerField(default=0)
    legacy = models.BooleanField(
        default=False,
        verbose_name=_("Выпущена переходом со старой ссылки"),
        help_text=_("Старая ссылка страницы ERP ведёт сюда: токен выводится из неё, второй записи не заводится"),
    )

    class Meta:
        verbose_name = _("Ссылка документа")
        verbose_name_plural = _("Ссылки документов")
        ordering = ["-created_at"]


class DocumentLinkEvent(models.Model):
    class Event(models.TextChoices):
        OPENED = "opened", _("Открыта")
        CODE_SENT = "code_sent", _("Код отправлен")
        CODE_USED = "code_used", _("Код подтверждён")
        CODE_FAILED = "code_failed", _("Неверный код")
        ACTION = "action", _("Действие")
        REVOKED = "revoked", _("Отозвана")

    link = models.ForeignKey(DocumentLink, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=20, choices=Event.choices)
    action = models.CharField(max_length=20, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Событие ссылки документа")
        verbose_name_plural = _("События ссылок документов")
        ordering = ["created_at", "id"]
