"""Integration models (CONTRACTS §0, §2, M3-ERP-01).

Хранит сопоставление сущностей CRM ↔ ERP и ключи идемпотентности:
- `CrmClientMapping`: crm_client_id ↔ parties.Company
- `CrmContactMapping`: crm_contact_id ↔ parties.Contact
- `CrmUserMapping`: crm_user_id ↔ CustomUser
- `IntegrationIdempotencyKey`: Idempotency-Key (UUID) с TTL 7 дней (Q-15, CONTRACTS §0)
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CrmClientMapping(models.Model):
    """Маппинг клиента CRM на компанию-контрагента в ERP."""

    crm_client_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name=_("CRM Client ID"),
        help_text=_("Идентификатор клиента в CRM"),
    )
    company = models.OneToOneField(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="crm_client_mapping",
        verbose_name=_("Компания ERP"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Маппинг клиента CRM")
        verbose_name_plural = _("Маппинги клиентов CRM")
        ordering = ["-created_at"]

    def __str__(self):
        return f"CRM Client #{self.crm_client_id} -> Company #{self.company_id}"


class CrmContactMapping(models.Model):
    """Маппинг контакта CRM на контакт контрагента в ERP."""

    crm_contact_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name=_("CRM Contact ID"),
        help_text=_("Идентификатор контакта в CRM"),
    )
    contact = models.OneToOneField(
        "parties.Contact",
        on_delete=models.CASCADE,
        related_name="crm_contact_mapping",
        verbose_name=_("Контакт ERP"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Маппинг контакта CRM")
        verbose_name_plural = _("Маппинги контактов CRM")
        ordering = ["-created_at"]

    def __str__(self):
        return f"CRM Contact #{self.crm_contact_id} -> Contact #{self.contact_id}"


class CrmUserMapping(models.Model):
    """Маппинг сотрудника CRM на пользователя бэк-офиса ERP."""

    crm_user_id = models.BigIntegerField(
        unique=True,
        db_index=True,
        verbose_name=_("CRM User ID"),
        help_text=_("Идентификатор пользователя в CRM"),
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="crm_user_mapping",
        verbose_name=_("Пользователь ERP"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Маппинг пользователя CRM")
        verbose_name_plural = _("Маппинги пользователей CRM")
        ordering = ["-created_at"]

    def __str__(self):
        return f"CRM User #{self.crm_user_id} -> User #{self.user_id}"


class IntegrationIdempotencyKey(models.Model):
    """Ключ идемпотентности для POST-запросов CRM → ERP.

    ERP хранит ключ 7 дней и возвращает первый ответ на повторный вызов
    с идентичным телом (OpenAPI erp-integration.yaml). При конфликте хэша — 409 IDEMPOTENCY_CONFLICT.
    """

    key = models.UUIDField(
        unique=True,
        db_index=True,
        verbose_name=_("Idempotency Key"),
    )
    path = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_("Путь запроса"),
    )
    request_hash = models.CharField(
        max_length=64,
        verbose_name=_("SHA-256 хэш тела запроса"),
    )
    response_status = models.PositiveIntegerField(
        verbose_name=_("HTTP статус ответа"),
    )
    response_body = models.JSONField(
        verbose_name=_("Тело ответа"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Дата создания"),
    )

    class Meta:
        verbose_name = _("Ключ идемпотентности интеграции")
        verbose_name_plural = _("Ключи идемпотентности интеграции")
        ordering = ["-created_at"]

    def is_expired(self, ttl_days: int = 7) -> bool:
        return timezone.now() > self.created_at + timezone.timedelta(days=ttl_days)

    def __str__(self):
        return f"IdempotencyKey({self.key}, status={self.response_status})"
