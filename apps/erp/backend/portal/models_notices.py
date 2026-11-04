"""Лента уведомлений кабинета — колокольчик контакта (NOTIFY-2, ADR-0023 п. 2).

Строка — на контакт-получатель: у каждого контакта своя прочитанность (Intercom, Slack). Текст не хранится: Cabinet
рендерит его на языке контакта по `text_key` и `params`. Повтор события не даёт второй строки — `dedup_key` уникален в
пределах контакта. Внешний канал выбирает маршрутизатор (`portal/services/notices.py`) и записывает решение в `channel`;
письмо (сразу или отложенное) ведёт `email_state`. Таблица событий и каналов — `docs/systems/erp/notifications.md`.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class NoticeChannel(models.TextChoices):
    #: Только колокольчик: событие не важное или контакту некуда писать.
    CABINET = "cabinet", _("Только кабинет")
    #: Бот CRM сам шлёт клиенту по событию ERP — ERP не дублирует (ADR-0023 п. 2).
    TELEGRAM = "telegram", _("Telegram (бот CRM)")
    #: Письмо уже ушло процессом документа (КП — каналы отправки ERP-11).
    SOURCE = "source", _("Письмо документа")
    EMAIL = "email", _("Письмо")
    #: Письмо через задержку, если уведомление не прочитано и контакт не заходил (ответ менеджера в чате).
    EMAIL_DELAYED = "email_delayed", _("Письмо с задержкой")


class NoticeEmailState(models.TextChoices):
    NONE = "", _("Письма нет")
    PENDING = "pending", _("Ждёт отправки")
    SENT = "sent", _("Отправлено")
    CANCELLED = "cancelled", _("Отменено")


class PortalNotice(models.Model):
    company = models.ForeignKey(
        "parties.Company", on_delete=models.CASCADE, related_name="portal_notices", verbose_name=_("Компания")
    )
    contact = models.ForeignKey(
        "parties.Contact", on_delete=models.CASCADE, related_name="portal_notices", verbose_name=_("Получатель")
    )
    kind = models.CharField(max_length=40, verbose_name=_("Вид"))
    group = models.CharField(max_length=30, verbose_name=_("Группа"))
    object_type = models.CharField(max_length=30, verbose_name=_("Тип объекта"))
    object_id = models.BigIntegerField(verbose_name=_("Id объекта в ERP"))
    object_number = models.CharField(max_length=100, blank=True, verbose_name=_("Номер объекта"))
    action = models.CharField(max_length=30, verbose_name=_("Действие"))
    text_key = models.CharField(max_length=60, verbose_name=_("Ключ текста"))
    params = models.JSONField(default=dict, blank=True, verbose_name=_("Параметры текста"))
    link = models.CharField(max_length=255, verbose_name=_("Ссылка в кабинете"))
    dedup_key = models.CharField(max_length=200, verbose_name=_("Ключ события"))
    read_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Прочитано"))
    channel = models.CharField(
        max_length=20, choices=NoticeChannel.choices, default=NoticeChannel.CABINET, verbose_name=_("Внешний канал")
    )
    email_state = models.CharField(
        max_length=10, choices=NoticeEmailState.choices, blank=True, default="", verbose_name=_("Письмо")
    )
    email_due_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name=_("Письмо — не раньше"))
    email_sent_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Письмо передано почте"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Уведомление кабинета")
        verbose_name_plural = _("Уведомления кабинета")
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["contact", "dedup_key"], name="portal_notice_contact_dedup_uniq"),
        ]
        indexes = [
            models.Index(fields=["contact", "read_at"], name="portal_notice_contact_read"),
        ]

    def __str__(self):
        return f"PortalNotice({self.kind}, contact={self.contact_id}, {self.object_type}#{self.object_id})"
