"""CRM counterparty relationship edge (Phase B, spec-remaining-2026-07-07 §2.1).

The keystone of the two-sided counterparty book: the CLIENT/SUPPLIER role is NOT a global label on
Company — the same organization is a *client* to seller A and a *supplier* to buyer B. The role
lives on this edge, relative to `owner_company` (whose book it is). That gives symmetric books —
a seller's «Клиенты» and a buyer's «Поставщики» — with one mechanism, and each owner sees only
their own edges (multi-seller confidentiality is preserved: the edge, its stage and its rollups
never leak across owners even when the counterparty Account is shared).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class RelationshipDirection(models.TextChoices):
    CLIENT = "CLIENT", _("Клиент (они покупают у нас)")
    SUPPLIER = "SUPPLIER", _("Поставщик (мы покупаем у них)")


class RelationshipStage(models.TextChoices):
    PROSPECT = "PROSPECT", _("Проспект")
    ACTIVE = "ACTIVE", _("Активный")
    DORMANT = "DORMANT", _("Спящий")
    LOST = "LOST", _("Потерян")


class RelationshipSource(models.TextChoices):
    LEAD = "LEAD", _("Лид с лендинга")
    OFFLINE_CREATED = "OFFLINE_CREATED", _("Заведён вручную (офлайн)")
    INBOUND_RFQ = "INBOUND_RFQ", _("Входящая заявка")
    SELF_REGISTERED = "SELF_REGISTERED", _("Саморегистрация")


class CounterpartyRelationship(models.Model):
    """One edge of the counterparty book: owner ↔ counterparty in one direction.

    Created automatically when companies first interact (RFQ routing, offline-client creation,
    lead conversion) — see crm/services/relationships.py. Rollups (deals_count/won_count/gmv,
    last_interaction_at) are denormalized so the book list renders without N+1; they are
    recomputed by explicit touch points + the `recompute_relationship_rollups` command.
    """

    owner_company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="counterparty_edges",
        verbose_name=_("Чья книга"),
    )
    counterparty_company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="counterparty_of",
        verbose_name=_("Контрагент"),
    )
    direction = models.CharField(
        max_length=10,
        choices=RelationshipDirection.choices,
        verbose_name=_("Роль контрагента"),
        help_text=_("Кем контрагент является ДЛЯ владельца книги (Rule 2: сравнивать по коду)"),
    )
    stage = models.CharField(
        max_length=10,
        choices=RelationshipStage.choices,
        default=RelationshipStage.PROSPECT,
        db_index=True,
        verbose_name=_("Стадия отношения"),
    )
    owner_member = models.ForeignKey(
        "accounts.CompanyMember",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_relationships",
        verbose_name=_("Владелец аккаунта"),
        help_text=_("Сотрудник команды, ответственный за отношение"),
    )
    source = models.CharField(
        max_length=20,
        choices=RelationshipSource.choices,
        default=RelationshipSource.INBOUND_RFQ,
        verbose_name=_("Источник"),
    )
    first_interaction_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Первое взаимодействие"))
    last_interaction_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("Последнее взаимодействие")
    )
    # Denormalized rollups for the list view (no N+1). Money in UZS (canonical, F7).
    deals_count = models.PositiveIntegerField(default=0, verbose_name=_("Сделок"))
    won_count = models.PositiveIntegerField(default=0, verbose_name=_("Выиграно"))
    gmv = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        verbose_name=_("GMV"),
        help_text=_("Сумма total_incl_vat выигранных сделок (UZS-канон)"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Отношение с контрагентом")
        verbose_name_plural = _("Отношения с контрагентами")
        ordering = ["-last_interaction_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_company", "counterparty_company", "direction"],
                name="uniq_relationship_edge",
            ),
        ]
        indexes = [
            models.Index(fields=["owner_company", "direction", "-last_interaction_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.owner_company} → {self.counterparty_company} [{self.direction}]"
