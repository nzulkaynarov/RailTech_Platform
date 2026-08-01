"""CompanyRole и CompanyMember (+QuerySet) — членство, права, never-orphan."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .core import seller_company_q


class CompanyMemberQuerySet(models.QuerySet):
    """Выборки по членству. Доступны и через обратную связь: `user.memberships.…`."""

    def in_seller_company(self):
        """Членства в компании-продавце. Флаги `is_active` / `can_sell` оставляем вызывающему —
        они про самого участника, а не про то, продавец ли компания."""
        return self.filter(seller_company_q("company"))


# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


# ────────────────────────────────────────────
# Основные модели
# ────────────────────────────────────────────


class CompanyRole(models.Model):
    """A company-defined role with an explicit permission set (the access matrix).

    World-standard Role+Permission-set: the company admin creates named roles and ticks
    permission checkboxes (accounts.constants.Permission). Replaces the cryptic
    can_sell/can_buy toggles. Scoped per company — each company has its own role policy.
    See Docs/dev/specs/rbac-roles-design-2026-06-25.md.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="roles",
        verbose_name=_("Компания"),
    )
    name = models.CharField(max_length=120, verbose_name=_("Название роли"))
    permissions = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Права"),
        help_text=_("Список кодов прав (accounts.constants.Permission)"),
    )
    is_system = models.BooleanField(
        default=False,
        verbose_name=_("Системная (Администратор компании)"),
        help_text=_("Полноправная роль администратора компании — нельзя удалить/урезать"),
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Кем создана"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Роль компании")
        verbose_name_plural = _("Роли компаний")
        ordering = ["-is_system", "name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_role_name_per_company"),
        ]

    def has_perm(self, code: str) -> bool:
        return self.is_system or code in (self.permissions or [])

    def __str__(self):
        return f"{self.name} — {self.company.name}"


class CompanyMember(models.Model):
    """
    Связь «Пользователь ↔ Компания» с ролью.
    Один пользователь может состоять в нескольких компаниях с разными ролями.
    """

    user = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Пользователь"),
        help_text=_("Участник компании"),
    )
    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name=_("Компания"),
        help_text=_("Организация, в которой состоит пользователь"),
    )
    role = models.ForeignKey(
        "accounts.WorkspaceRole",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("Роль в компании"),
        help_text=_("Функциональная роль внутри рабочего пространства"),
    )
    # New per-company role with an explicit permission set (Role+Permission-set model,
    # rbac-roles-design-2026-06-25). Additive: when set it drives access; `role`
    # (legacy WorkspaceRole) is kept during the transition and as a derivation fallback.
    company_role = models.ForeignKey(
        "accounts.CompanyRole",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        verbose_name=_("Роль (с правами)"),
        help_text=_("Роль компании с набором прав; назначается администратором компании"),
    )
    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("Основная компания"),
        help_text=_("Основное рабочее пространство пользователя"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Активен"),
        help_text=_("Деактивированные участники не имеют доступа к компании"),
    )
    # Per-member capabilities. The company's OWNER distributes selling/buying
    # rights inside the team. Defaults are True so existing memberships keep
    # their current access; OWNER can turn flags off explicitly.
    can_sell = models.BooleanField(
        default=True,
        verbose_name=_("Может продавать"),
        help_text=_("Разрешено управлять каталогом и офферами от лица компании. " "Выключается владельцем компании."),
    )
    can_buy = models.BooleanField(
        default=True,
        verbose_name=_("Может покупать"),
        help_text=_(
            "Разрешено создавать заявки/сделки и принимать bid'ы от лица " "компании. Выключается владельцем компании."
        ),
    )
    joined_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Дата вступления"),
    )

    objects = models.Manager.from_queryset(CompanyMemberQuerySet)()

    class Meta:
        verbose_name = _("Участник компании")
        verbose_name_plural = _("Участники компаний")
        unique_together = [("user", "company")]
        ordering = ["-is_primary", "joined_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_primary=True),
                name="unique_primary_company_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} → {self.company.name} [{self.role}]"
