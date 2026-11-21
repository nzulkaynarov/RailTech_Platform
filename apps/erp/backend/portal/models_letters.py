"""Официальные письма компании в кабинете — проекция реестра EDS (ЛИД-8, ADR-0026).

Строка — письмо одной компании-контрагента: наше исходящее (`out`, ИСХ) или её входящее (`in`, ВХ — квитанция о
регистрации). Источник — события EDS `document.registered.v2` (ИСХ с блоком `letter`) и `letter.registered.v2` (ВХ).
Чьё письмо — только по сделке ERP или точному ИНН; совпадения нет — строки нет. Резолюций, исполнителей и черновиков
EDS здесь нет. Файл исходящего ERP читает у EDS по запросу кабинета (сервисный токен, ADR-0026 п. 4), здесь не хранит.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class LetterDirection(models.TextChoices):
    #: Письмо компании нам: в кабинете — квитанция о регистрации (номер ВХ, дата).
    IN = "in", _("Входящее")
    #: Наше письмо компании: номер ИСХ, файл.
    OUT = "out", _("Исходящее")


class LetterState(models.TextChoices):
    #: Входящее зарегистрировано, ответа ещё нет.
    REGISTERED = "registered", _("Зарегистрировано")
    #: На входящее ушёл наш ответ (ИСХ «в ответ на»).
    ANSWERED = "answered", _("Отвечено")
    #: Исходящее отправлено.
    SENT = "sent", _("Отправлено")


class PortalLetter(models.Model):
    company = models.ForeignKey(
        "parties.Company", on_delete=models.CASCADE, related_name="portal_letters", verbose_name=_("Компания")
    )
    deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="portal_letters",
        verbose_name=_("Проект"),
    )
    direction = models.CharField(max_length=3, choices=LetterDirection.choices, verbose_name=_("Направление"))
    state = models.CharField(max_length=16, choices=LetterState.choices, verbose_name=_("Состояние"))
    #: id письма (`in`) или документа (`out`) в EDS: ключ идемпотентности проекции.
    eds_id = models.UUIDField(unique=True, verbose_name=_("ID в EDS"))
    number = models.CharField(
        max_length=32, verbose_name=_("Номер"), help_text=_("Входящий или исходящий номер по нумерации EDS")
    )
    subject = models.CharField(max_length=300, verbose_name=_("Тема"))
    #: Дата письма: получения (`in`) или регистрации при отправке (`out`).
    date = models.DateField(verbose_name=_("Дата"))
    registered_at = models.DateTimeField(verbose_name=_("Зарегистрировано"))
    #: Исходящее «в ответ на»: номер ВХ и id письма EDS; у входящего — номер нашего ответа.
    reply_number = models.CharField(max_length=32, blank=True, default="", verbose_name=_("Ответ или «в ответ на»"))
    in_reply_to_eds_id = models.UUIDField(null=True, blank=True, verbose_name=_("В ответ на (ID письма EDS)"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Письмо в кабинете")
        verbose_name_plural = _("Письма в кабинете")
        ordering = ["-registered_at", "-id"]
        indexes = [models.Index(fields=["company", "-registered_at"], name="portal_letter_company_idx")]

    def __str__(self) -> str:
        return f"{self.number} · {self.subject}"
