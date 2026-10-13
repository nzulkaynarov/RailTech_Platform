"""One-time email acceptance codes for the public КП page (Wave A, offline acceptance).

An anonymous visitor holding the 256-bit public link may VIEW the client projection freely,
but ACCEPTING the offer (коммерческий акцепт — a commercial acceptance with an audit trail,
NOT a qualified e-signature) is a value-bearing action gated by proof of control of the deal's
contact email (PandaDoc pattern: view is open, the binding action is verified).

Security shape (adversarial):
  * The code is stored ONLY as a sha256 HASH — never in plaintext, never emailed back to us.
  * Short expiry (~15 min) + single-use (`consumed_at`) + an attempt cap (`attempts`).
  * The recipient email is resolved from the QUOTE'S OWN deal, never from request input — so the
    endpoint cannot be used to enumerate accounts or redirect a code to an attacker's address.
  * Brute force over the 6-digit space is bounded by: attempt cap + expiry + endpoint throttle +
    the 256-bit token already required to reach the quote at all.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class QuoteAcceptanceCode(models.Model):
    """A single-use, hashed, short-lived email code proving a contact may accept a specific КП."""

    quote = models.ForeignKey(
        "crm.Quote",
        on_delete=models.CASCADE,
        related_name="acceptance_codes",
        verbose_name=_("КП"),
        help_text=_("Коммерческое предложение, к которому привязан код акцепта"),
    )
    # The recipient this code was issued to — resolved from the deal (deal.client/contact email),
    # NEVER from request input. Stored lowercased for audit and to bind the code to one address.
    email = models.EmailField(
        verbose_name=_("Email получателя"),
        help_text=_("Адрес, на который отправлен код (взят из сделки, не из запроса)"),
    )
    # sha256(code) — never the plaintext code. Verified with a constant-time hash compare.
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
    # Best-effort audit of who requested/consumed the code (client-controllable header — NOT a
    # trust anchor, kept for the acceptance audit trail only).
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
