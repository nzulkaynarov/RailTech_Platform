"""One-time email acceptance codes for the public КП page."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class QuoteAcceptanceCode(models.Model):
    """A single-use, hashed, short-lived email code proving a contact may accept a specific КП."""

    quote = models.ForeignKey(
        "sales.Quote",
        on_delete=models.CASCADE,
        related_name="acceptance_codes",
        verbose_name=_("КП"),
        help_text=_("Коммерческое предложение, к которому привязан код акцепта"),
    )
    email = models.EmailField(
        verbose_name=_("Email получателя"),
        help_text=_("Адрес, на который отправлен код (взят из сделки, не из запроса)"),
    )
    code_hash = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("Хэш кода"),
        help_text=_("sha256 одноразового кода акцепта (открытый код никогда не хранится)"),
    )
    attempts = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Попыток ввода"),
        help_text=_("Число неверных попыток ввода — код блокируется по достижении лимита"),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Создан"),
    )
    expires_at = models.DateTimeField(
        db_index=True,
        verbose_name=_("Истекает"),
        help_text=_("Момент, после которого код недействителен (короткий TTL)"),
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Использован"),
        help_text=_("Момент успешного акцепта — код одноразовый и больше не принимается"),
    )
    request_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP запроса"),
        help_text=_("IP, с которого запрошен код (для журнала акцепта)"),
    )

    class Meta:
        verbose_name = _("Код акцепта КП")
        verbose_name_plural = _("Коды акцепта КП")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["quote", "created_at"]),
        ]

    def __str__(self):
        return f"AcceptanceCode(quote={self.quote_id}, consumed={self.consumed_at is not None})"
