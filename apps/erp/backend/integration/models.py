"""Integration models (CONTRACTS §0, §2, M3-ERP-01).

Хранит сопоставление сущностей CRM ↔ ERP и ключи идемпотентности:
- `CrmClientMapping`: crm_client_id ↔ parties.Company
- `CrmContactMapping`: crm_contact_id ↔ parties.Contact
- `CrmUserMapping`: crm_user_id ↔ CustomUser
- `PartnerCrmLink`: состояние «клиент партнёра в CRM» до сопоставления (PART-CRM): запрошен или конфликт
- `DeferredRequestEvent`: заявка партнёра, чей `request.created` ждёт сопоставления клиента CRM (PART-CRM)
- `IntegrationIdempotencyKey`: Idempotency-Key (UUID) с TTL 7 дней (Q-15, CONTRACTS §0)
- `PairingCode`, `ServiceCredential`: сопряжение с CRM одним кодом — одноразовый код (хеш) и сервисные
  токены/секрет вебхуков, зашифрованные в БД (M3-ERP-05)
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
    # Заявка, созданная самой передачей (FIX-31): повтор отдаёт её же, а не «самую старую сделку компании»
    # (у компании, найденной по ИНН, есть и сделки сотрудников).
    handoff_deal = models.ForeignKey(
        "sales.Deal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Заявка передачи"),
        help_text=_("Заявка, созданная при передаче клиента из CRM"),
    )
    # Проверка сопоставления человеком (PART-CRM). Сопоставление, созданное передачей из CRM по совпадению ИНН с уже
    # существующей компанией (FIX-31: журнал `company.linked_by_inn`), — НЕПРОВЕРЕННОЕ (`verified_at` пусто): опечатка в ИНН
    # связала бы компанию с чужим клиентом. Для новой компании, ответа CRM `linked` и подтверждённое сотрудником — проверенное
    # (по умолчанию «сейчас»: прежние сопоставления и все прочие места создания остаются проверенными).
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        default=timezone.now,
        verbose_name=_("Проверено"),
        help_text=_("Пусто — связано по совпадению ИНН и ещё не подтверждено человеком"),
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кто подтвердил"),
    )
    crm_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Название клиента в CRM"),
        help_text=_("Как клиент назван в передаче из CRM: показывается сотруднику при проверке сопоставления"),
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
    # Последний провижининг: {"role", "permissions", "role_codes"}. Нужен, чтобы привязать сотрудника к своей компании,
    # созданной ПОЗЖЕ провижининга (мастер первого запуска, FIX-P1-2): без неё ролям взяться неоткуда. NULL —
    # сопоставление создано до этого поля (роль восстанавливается по `is_superuser`, права — минимальные).
    provision_snapshot = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("Последний провижининг"),
        help_text=_("Роль, права и системные роли из последнего провижининга CRM"),
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


class CrmProjectionKind(models.TextChoices):
    CLIENT = "client", _("Клиент CRM")
    CONTACT = "contact", _("Контакт CRM")


class CrmProjectionState(models.Model):
    """Какой снимок CRM применён к проекции ERP (B3, ADR-0015 п. 5, CONTRACTS §9): порядок событий не гарантирован.

    События CRM `client.updated` и `contact.*` — снимки с `updated_at` (`deleted_at` у удаления): более старый снимок
    уже применённого не применяется. `applied_at` — момент самого нового применённого снимка; `deleted` — контакт
    удалён (надгробие: поздний `contact.updated` не воскрешает контакт, а ERP-контакта уже нет).
    """

    kind = models.CharField(max_length=16, choices=CrmProjectionKind.choices)
    crm_id = models.BigIntegerField(verbose_name=_("Идентификатор в CRM"))
    applied_at = models.DateTimeField(verbose_name=_("updated_at / deleted_at применённого снимка"))
    deleted = models.BooleanField(default=False, verbose_name=_("Удалён в CRM"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Состояние проекции CRM")
        verbose_name_plural = _("Состояния проекций CRM")
        constraints = [models.UniqueConstraint(fields=["kind", "crm_id"], name="int_crm_projection_uniq")]

    def __str__(self):
        return f"CrmProjectionState({self.kind}#{self.crm_id}, {self.applied_at:%Y-%m-%d %H:%M:%S}, deleted={self.deleted})"


class PairingCode(models.Model):
    """Одноразовый код сопряжения с CRM (M3-ERP-05, CONTRACTS §2 «Сопряжение»).

    В базе — только хеш кода (SHA-256 нормализованного кода): по БД код восстановить нельзя, а у кода 59 бит
    энтропии. Код действует до `expires_at` и один раз (`used_at`); новый выпуск гасит прежний неиспользованный.
    """

    code_hash = models.CharField(max_length=64, unique=True, verbose_name=_("Хеш кода"))
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True, verbose_name=_("Действует до"))
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Использован или заменён"),
        help_text=_("Заполнено, когда код принят CRM или погашен новым выпуском"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name=_("Кто выпустил"),
        help_text=_("Пусто — выпущен командой `manage.py pairing_code`"),
    )

    class Meta:
        verbose_name = _("Код сопряжения с CRM")
        verbose_name_plural = _("Коды сопряжения с CRM")
        ordering = ["-created_at"]

    def __str__(self):
        return f"PairingCode(#{self.pk}, до {self.expires_at:%Y-%m-%d %H:%M})"


class PairingState(models.Model):
    """Постоянное состояние сопряжения (одна строка, pk=1).

    `bootstrap_used_at` — когда состоялось первое сопряжение. С этого момента «первое сопряжение без кода» закрыто
    НАВСЕГДА (ADR-0009): флаг переживает очистку токенов, дальше — только код из ERP.
    """

    bootstrap_used_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Первое сопряжение состоялось"))

    class Meta:
        verbose_name = _("Состояние сопряжения с CRM")
        verbose_name_plural = _("Состояние сопряжения с CRM")

    def __str__(self):
        return f"PairingState(bootstrap_used_at={self.bootstrap_used_at})"


class CredentialSlot(models.TextChoices):
    CRM_TO_ERP = "crm_to_erp", _("Токен CRM→ERP")
    CRM_TO_ERP_PREVIOUS = "crm_to_erp_previous", _("Прежний токен CRM→ERP (переход при ротации)")
    ERP_TO_CRM = "erp_to_crm", _("Токен ERP→CRM")
    WEBHOOK_SECRET = "webhook_secret", _("Секрет подписи вебхуков")
    WEBHOOK_SECRET_PREVIOUS = "webhook_secret_previous", _("Прежний секрет сопряжения (переход при ротации)")


class ServiceCredential(models.Model):
    """Секрет шва CRM ↔ ERP, выданный сопряжением (M3-ERP-05): значение шифровано, в API и логи не уходит.

    Fernet, ключ выводится из `SECRET_KEY` (как секрет 2FA). Смена `SECRET_KEY` делает значения нечитаемыми —
    тогда ERP возвращается к секретам из `.env` и пишет ошибку в лог, а CRM сопрягается заново новым кодом.
    `created_at` строки `crm_to_erp` — время сопряжения; `rotated_at` — последняя ротация.
    """

    slot = models.CharField(max_length=32, choices=CredentialSlot.choices, unique=True)
    ciphertext = models.TextField(verbose_name=_("Шифртекст"))
    last4 = models.CharField(max_length=4, blank=True, default="", verbose_name=_("Последние 4 символа"))
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Действует до"),
        help_text=_("Только для прежнего токена: после этого срока он не принимается"),
    )
    rotated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Время последней ротации"),
        help_text=_("Только для строки токена CRM→ERP"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Сервисный секрет шва CRM ↔ ERP")
        verbose_name_plural = _("Сервисные секреты шва CRM ↔ ERP")
        ordering = ["slot"]

    def __str__(self):
        return f"ServiceCredential({self.slot})"


class PartnerCrmStatus(models.TextChoices):
    REQUESTED = "requested", _("Запрошен")
    PENDING_CONFIRMATION = "pending_confirmation", _("Ждёт подтверждения менеджера")
    HELD = "held", _("Удержано после передачи клиента")
    CONFLICT = "conflict", _("Конфликт")


class PartnerCrmLink(models.Model):
    """Что известно о клиенте CRM для приглашённого партнёра, пока сопоставления `CrmClientMapping` нет (PART-CRM).

    «Заведён» живёт в самом сопоставлении, поэтому здесь только два состояния: `requested` — ERP опубликовала
    `partner.client_requested` (дата последнего запроса) и ждёт ответ; `conflict` — CRM ответила, что найденный клиент уже
    сопоставлен другой компании ERP (`crm_client_id` — этот клиент, `conflict_company_id` — та компания);
    `pending_confirmation` — CRM нашла похожего клиента без сопоставления и ждёт решения менеджера («Это та же компания»
    или «Нет — завести нового»; `crm_client_id` — найденный клиент). Строка не заменяет сопоставление: когда оно
    появилось, состояние читается из него. `held` — передача клиента из CRM нашла компанию партнёра по ИНН: сопоставление не
    создано, заявки удержаны до повторного приглашения (`crm_client_id` — клиент передачи).
    """

    company = models.OneToOneField(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="partner_crm_link",
        verbose_name=_("Компания ERP"),
    )
    status = models.CharField(max_length=24, choices=PartnerCrmStatus.choices, default=PartnerCrmStatus.REQUESTED)
    crm_client_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Клиент CRM"),
        help_text=_("При конфликте — найденный клиент CRM, уже занятый другой компанией"),
    )
    conflict_company_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Другая компания ERP"),
        help_text=_("При конфликте — компания ERP, с которой клиент CRM уже сопоставлен"),
    )
    requested_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Клиент партнёра в CRM")
        verbose_name_plural = _("Клиенты партнёров в CRM")

    def __str__(self):
        return f"PartnerCrmLink(company={self.company_id}, {self.status})"


class DeferredRequestEvent(models.Model):
    """Заявка партнёра из кабинета, чей `request.created` не ушёл: компания не сопоставлена клиенту CRM (PART-CRM).

    Строка пишется в той же транзакции, что и заявка. После сопоставления ERP публикует событие и ставит `published_at`
    (повтор ничего не публикует). Заявку клиента с сопоставлением строка не создаёт — её событие уходит сразу.
    """

    deal = models.OneToOneField(
        "sales.Deal",
        on_delete=models.CASCADE,
        related_name="deferred_request_event",
        verbose_name=_("Заявка"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Отложенное событие заявки")
        verbose_name_plural = _("Отложенные события заявок")
        indexes = [models.Index(fields=["published_at"], name="deferred_request_pending")]

    def __str__(self):
        return f"DeferredRequestEvent(deal={self.deal_id}, published={self.published_at is not None})"


class CommercialSigningRequest(models.Model):
    """Запрос подписи коммерческого документа в EDS (SIGN-4, FX-10): какая редакция ушла на подпись и чем закончилось."""

    class Status(models.TextChoices):
        PENDING = "pending", _("На подписи")
        SIGNED = "signed", _("Подписан")
        REJECTED = "rejected", _("Отказ")
        STALE = "stale", _("Документ изменён")

    kind = models.CharField(max_length=16)
    object_id = models.BigIntegerField()
    number = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64, help_text=_("Отпечаток редакции документа на момент запроса"))
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    comment = models.TextField(blank=True, default="")
    signer_name = models.CharField(max_length=255, blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["kind", "object_id"], name="integration_kind_obj_idx")]
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "object_id"],
                condition=models.Q(status="pending"),
                name="uq_commercial_signing_one_pending",
            )
        ]
