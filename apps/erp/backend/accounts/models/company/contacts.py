"""Contact (офлайн-клиенты, Deal.contact)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Contact(models.Model):
    """A person at a client company who has NO platform login (the CRM "Contact").

    World-standard Account(Company)+Contact model: a seller can record the people they
    deal with at an offline client and reuse them across deals. Distinct from
    CompanyMember (a registered user). One company has many contacts.
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name=_("Компания"),
        help_text=_("Организация, к которой относится контакт"),
    )
    name = models.CharField(max_length=255, verbose_name=_("ФИО"))
    email = models.EmailField(blank=True, verbose_name=_("Email"))
    phone = models.CharField(max_length=50, blank=True, verbose_name=_("Телефон"))
    position = models.CharField(max_length=255, blank=True, verbose_name=_("Должность"))
    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("Основной контакт"),
        help_text=_("Контакт по умолчанию для отправки КП"),
    )
    created_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_contacts",
        verbose_name=_("Кем создан"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Контакт")
        verbose_name_plural = _("Контакты")
        ordering = ["-is_primary", "name"]

    def clean(self):
        # World-practice rule: a contact must be reachable by at least one channel.
        from django.core.exceptions import ValidationError

        if not (self.email or self.phone):
            raise ValidationError(_("Укажите email или телефон контакта."))

    def __str__(self):
        return f"{self.name} — {self.company.name}"
