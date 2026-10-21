"""CompanyRole и CompanyMember (+QuerySet) — членство, права, never-orphan."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .core import seller_company_q


class CompanyMemberQuerySet(models.QuerySet):
    """Выборки по членству. Доступны и через обратную связь: `user.memberships.…`."""

    def create(self, **kwargs):
        """`company_roles=[...]` прямо в `create()` — роли бэк-офиса (M2M) назначаются после записи
        участника; так фикстуры и сервисы создают сотрудника с ролями одной строкой."""
        roles = [role for role in (kwargs.pop("company_roles", None) or []) if role is not None]
        member = super().create(**kwargs)
        if roles:
            member.company_roles.add(*roles)
        return member

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
    """Роль бэк-офиса с набором прав (M1-ERP-05; ERPNext «Role + Role Permission», Odoo «группа»).

    Права — коды `accounts.constants.Permission`. У сотрудника может быть несколько ролей
    (`CompanyMember.company_roles`), действует объединение прав. Системные роли (`is_system`,
    `code` из `BackofficeRoleCode`) сеются для своей компании и не меняются; свои роли компания
    собирает в «Настройках → Команда и роли». «Администратор» — не роль, а `is_superuser`.
    """

    company = models.ForeignKey(
        "parties.Company",
        on_delete=models.CASCADE,
        related_name="roles",
        verbose_name=_("Компания"),
    )
    name = models.CharField(max_length=120, verbose_name=_("Название роли"))
    code = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name=_("Код"),
        help_text=_("Код системной роли (BackofficeRoleCode); пусто у ролей, созданных компанией"),
    )
    permissions = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Права"),
        help_text=_("Список кодов прав (accounts.constants.Permission)"),
    )
    is_system = models.BooleanField(
        default=False,
        verbose_name=_("Системная"),
        help_text=_("Роль-шаблон бэк-офиса — имя и права не меняются, удалить нельзя"),
    )
    managed_by_crm = models.BooleanField(
        default=False,
        verbose_name=_("Управляется CRM"),
        help_text=_(
            "Роль «CRM Sync: <e-mail>» ведёт провижининг из CRM (integration.services.provision): права и состав "
            "приходят из CRM, в «Настройках → Команда» её нельзя назначить, изменить или снять"
        ),
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
            models.UniqueConstraint(
                fields=["company", "code"], condition=~models.Q(code=""), name="unique_role_code_per_company"
            ),
        ]

    def has_perm(self, code: str) -> bool:
        return code in (self.permissions or [])

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
        "parties.Company",
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
    # Роли бэк-офиса с правами (M1-ERP-05): несколько на человека, права — объединение.
    # `role` (WorkspaceRole) — переходная должность для приглашения; доступ не определяет.
    company_roles = models.ManyToManyField(
        "accounts.CompanyRole",
        blank=True,
        related_name="members",
        verbose_name=_("Роли (с правами)"),
        help_text=_("Роли бэк-офиса; права складываются"),
    )
    # Какие из `company_roles` выданы провижинингом из CRM (`role_codes`, FIX-63, Q-FIX50-1 (1)): только их
    # следующий провижининг и отзыв доступа снимают без участия человека; роли, назначенные вручную в «Команде»,
    # сюда не попадают и не затираются.
    crm_granted_roles = models.ManyToManyField(
        "accounts.CompanyRole",
        blank=True,
        related_name="crm_granted_members",
        verbose_name=_("Роли, выданные из CRM"),
        help_text=_("Системные роли, которые CRM выдала провижинингом (`role_codes`); снимаются тоже из CRM"),
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
    # Per-member capability. The company's OWNER distributes selling rights inside the
    # team. Default is True so existing memberships keep their current access.
    can_sell = models.BooleanField(
        default=True,
        verbose_name=_("Может продавать"),
        help_text=_("Разрешено управлять каталогом и офферами от лица компании. " "Выключается владельцем компании."),
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
