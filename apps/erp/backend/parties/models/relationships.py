"""Отношение компании к нам (ADR-0022): кем она работает с нами и открыт ли ей кабинет.

Тип компании (`CompanyType`) говорит, кто она вообще (клиент, поставщик, изготовитель, своя компания). Отношение — отдельная
запись «компания — роль — статус»: его заводит сотрудник, оно приглашено, активно или приостановлено, и именно оно
открывает кабинет не-клиентам. Клиенты на срезе не переводятся: доступ клиента по-прежнему даёт тип CLIENT.
Роль — значение справочника `RelationshipRole`; новая роль — новая строка справочника и шаблон модулей
(`portal/services/roles.py`), без правок кода входа. Партнёр (изготовитель, поставщик, принципал) — одна роль `partner`;
вид партнёра (`kind`) — необязательная метка и на права не влияет. Права партнёра — список включённых модулей на отношении
(`modules`): его меняет сотрудник в Платформе, история правок — pghistory.
"""

import pghistory
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from catalog.constants import PriceVisibility


class RelationshipRole(models.TextChoices):
    """Роль компании в кабинете: клиент и партнёр (ADR-0022 п. 1; решение владельца 2026-11-04)."""

    CLIENT = "client", _("Клиент")
    PARTNER = "partner", _("Партнёр")


class PartnerKind(models.TextChoices):
    """Вид партнёра — метка отношения для людей и отчётов, на права не влияет."""

    MANUFACTURER = "manufacturer", _("Изготовитель")
    SUPPLIER = "supplier", _("Поставщик")
    PRINCIPAL = "principal", _("Принципал")
    OTHER = "other", _("Другое")


class RelationshipStatus(models.TextChoices):
    INVITED = "invited", _("Приглашён")
    ACTIVE = "active", _("Активен")
    SUSPENDED = "suspended", _("Приостановлен")


#: Статусы, при которых вход открыт: приглашённый входит впервые (первый вход переводит отношение в `active`).
ENTRY_STATUSES = (RelationshipStatus.INVITED, RelationshipStatus.ACTIVE)


@pghistory.track()  # аудит: кто и когда пригласил, приостановил, вернул доступ
class CompanyRelationship(models.Model):
    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="relationships",
        verbose_name=_("Компания"),
    )
    role = models.CharField(max_length=20, choices=RelationshipRole.choices, verbose_name=_("Роль"))
    kind = models.CharField(
        max_length=20,
        choices=PartnerKind.choices,
        blank=True,
        default="",
        verbose_name=_("Вид партнёра"),
        help_text=_("Необязательная метка; на права не влияет"),
    )
    modules = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Включённые модули"),
        help_text=_("Разделы кабинета партнёра; допустимые — из шаблона роли (`portal/services/roles.py`)"),
    )
    status = models.CharField(
        max_length=20,
        choices=RelationshipStatus.choices,
        default=RelationshipStatus.INVITED,
        verbose_name=_("Статус"),
    )
    #: PART-3: показывать ли клиентам цены товаров этого партнёра в каталоге — по договорённости с ним. Пусто — как у
    #: компании (`CompanySettings.catalog_price_visibility`); своя политика карточки сильнее (`catalog.policy`).
    catalog_price_visibility = models.CharField(
        max_length=16,
        choices=PriceVisibility.choices,
        blank=True,
        default="",
        verbose_name=_("Цены товаров партнёра в каталоге"),
        help_text=_("Пусто — как у компании; иначе показывать или «по запросу». Своя политика карточки сильнее."),
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Ответственный сотрудник"),
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто пригласил"),
    )
    invited_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Приглашён"))
    activated_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Первый вход"))
    suspended_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Приостановлен"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Отношение компании")
        verbose_name_plural = _("Отношения компаний")
        constraints = [
            models.UniqueConstraint(fields=["company", "role"], name="uniq_company_relationship_role"),
        ]

    def __str__(self):
        return f"{self.company_id}:{self.role}:{self.status}"
