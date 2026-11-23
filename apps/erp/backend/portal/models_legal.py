"""Оферта и политика Кабинета: редакции и акцепты контактов (ДВ-5).

Редакция — один документ (`privacy` или `terms`) с текстом на трёх языках. Опубликованная редакция не правится: новый
текст — новая редакция. «Действующая» — опубликованная и не снятая; такая у каждого вида одна (частичное ограничение
уникальности). Акцепт — факт «контакт принял именно эту редакцию»: кто, когда, на каком языке видел текст, откуда.
Пока ни одна редакция не опубликована, кабинет открыт как раньше (`portal/services/legal.py`).
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class LegalKind(models.TextChoices):
    PRIVACY = "privacy", _("Политика обработки персональных данных")
    TERMS = "terms", _("Условия использования (оферта)")


class LegalEdition(models.Model):
    kind = models.CharField(max_length=10, choices=LegalKind.choices, verbose_name=_("Вид документа"))
    label = models.CharField(max_length=40, verbose_name=_("Редакция"), help_text=_("Например, 2026-11-23"))
    content = models.JSONField(
        default=dict,
        verbose_name=_("Текст"),
        help_text=_("{title:{ru,uz,en}, lead:{…}, sections:[{title:{…}, body:{…}}]}; подстановки {{company.*}}"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name=_("Опубликована"))
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    retired_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Заменена новой"))

    class Meta:
        verbose_name = _("Редакция документа Кабинета")
        verbose_name_plural = _("Редакции документов Кабинета")
        ordering = ["kind", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "label"], name="portal_legal_edition_kind_label_uniq"),
            models.UniqueConstraint(
                fields=["kind"],
                condition=models.Q(published_at__isnull=True),
                name="portal_legal_edition_one_draft_per_kind",
            ),
            models.UniqueConstraint(
                fields=["kind"],
                condition=models.Q(published_at__isnull=False, retired_at__isnull=True),
                name="portal_legal_edition_one_current_per_kind",
            ),
        ]

    @property
    def status(self) -> str:
        if self.published_at is None:
            return "draft"
        return "retired" if self.retired_at else "current"

    def __str__(self):
        return f"{self.kind} {self.label} ({self.status})"


class LegalAcceptance(models.Model):
    contact = models.ForeignKey(
        "parties.Contact", on_delete=models.CASCADE, related_name="legal_acceptances", verbose_name=_("Контакт")
    )
    company = models.ForeignKey(
        "parties.Company", on_delete=models.CASCADE, related_name="legal_acceptances", verbose_name=_("Компания")
    )
    edition = models.ForeignKey(LegalEdition, on_delete=models.PROTECT, related_name="acceptances")
    accepted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    language = models.CharField(max_length=2, verbose_name=_("Язык текста, который видел контакт"))
    auth_method = models.CharField(max_length=20, blank=True, verbose_name=_("Способ входа"))
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("IP адрес"))
    user_agent = models.TextField(blank=True, verbose_name=_("User Agent"))

    class Meta:
        verbose_name = _("Акцепт редакции")
        verbose_name_plural = _("Акцепты редакций")
        ordering = ["-accepted_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["contact", "edition"], name="portal_legal_acceptance_contact_edition_uniq")
        ]
