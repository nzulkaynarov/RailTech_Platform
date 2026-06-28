"""Platform Operator sub-role (ADR-0004 G1).

The Platform Operator plane (SystemRole.ADMIN, no CompanyMember) is split into
least-privilege sub-roles. Unlike CompanyRole this is PLATFORM-scoped — there is no
company FK; an OperatorRole governs platform-staff capabilities, never tenant
operations. The five presets are seeded (accounts.constants.OPERATOR_ROLE_TEMPLATES);
SUPER_OPERATOR is the immutable full-rights role (= the legacy single ADMIN).
See Docs/adr/0004-three-admin-planes-core.md.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class OperatorRole(models.Model):
    """A platform-operator sub-role with an explicit capability set (the operator
    access matrix). Mirrors the company Role+Permission-set, but platform-global."""

    code = models.SlugField(
        max_length=40,
        unique=True,
        verbose_name=_("Код роли"),
        help_text=_("Стабильный код (accounts.constants.OperatorRoleCode); сравнение в коде по нему"),
    )
    name = models.CharField(max_length=120, verbose_name=_("Название роли"))
    permissions = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Права"),
        help_text=_("Список кодов прав (accounts.constants.OperatorPermission)"),
    )
    is_system = models.BooleanField(
        default=False,
        verbose_name=_("Системная (Супероператор)"),
        help_text=_("Полноправная роль оператора — нельзя удалить/урезать"),
    )
    description = models.TextField(blank=True, default="", verbose_name=_("Описание"))
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
        verbose_name = _("Роль оператора")
        verbose_name_plural = _("Роли операторов")
        ordering = ["-is_system", "name"]

    def has_perm(self, code: str) -> bool:
        return self.is_system or code in (self.permissions or [])

    def __str__(self):
        return f"{self.name} ({self.code})"
