from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# The document kinds whose {type} token is company-editable, in preview order. The values
# are the SHIPPED defaults (kept equal to the historical hardcoded labels → zero visual diff
# for companies that never touch them); each is overridable per company via
# DocumentNumberingScheme.type_labels so nothing about the label is hardcoded downstream.
NUMBERING_TYPE_CODES = ("KP", "CT", "INV", "ACT", "DOC")
DEFAULT_TYPE_LABELS = {"KP": "КП", "CT": "CT", "INV": "INV", "ACT": "ACT", "DOC": "DOC"}


def default_type_labels():
    """Fresh copy of the shipped type-label map (JSONField default must be a callable)."""
    return dict(DEFAULT_TYPE_LABELS)


class DocumentSequence(models.Model):
    """Race-safe, gap-free, per-period document numbering counter.

    Replaces the `Model.objects.filter(year=...).count() + 1` pattern, which
    races under concurrency: two requests read the same count and mint the same
    number → IntegrityError (the `number` unique constraint) → a 500. One row
    per (company, doc_type, period); `next_document_number()` locks it with
    select_for_update so concurrent callers serialize and each gets a distinct,
    sequential number.

    doc_type is a short code: "INV" (invoice), "ACT", "CT" (contract), "KP", "DOC".

    Period scope (N1): the counter is scoped by `period` — a string derived from the
    company's DocumentNumberingScheme.reset_period ("ALL" for never, "2026" for yearly,
    "2026-07" for monthly). `year` is retained for informational/back-compat use (and is
    auto-derived into `period` on save when `period` is left blank, so rows created with
    only `year=` — legacy call sites and the 0037 backfill — keep working).

    Per-company numbering: `company` scopes the counter so each selling company keeps
    its OWN gap-free sequence (ACME's contracts and BETA's contracts both start at
    00001 without colliding). company=NULL is the platform/legacy counter — existing
    rows keep it untouched. On Postgres a NULL is DISTINCT under a UniqueConstraint, so
    the platform path is NOT uniquely constrained across rows; that's intentional (only
    one NULL-company row per (doc_type, period) is ever created via select_for_update
    get_or_create, which serialises the first insert).
    """

    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_sequences",
        verbose_name=_("Компания"),
        help_text=_("Компания-эмитент; NULL — платформенный/устаревший счётчик"),
    )
    doc_type = models.CharField(max_length=16, verbose_name=_("Тип документа"))
    year = models.PositiveIntegerField(verbose_name=_("Год"))
    period = models.CharField(
        max_length=16,
        blank=True,
        default="",
        verbose_name=_("Период сброса"),
        help_text=_("Ключ периода счётчика: «ALL» (без сброса), «2026» (год) или «2026-07» (месяц)"),
    )
    last_value = models.PositiveIntegerField(default=0, verbose_name=_("Последний номер"))

    class Meta:
        verbose_name = _("Счётчик нумерации документов")
        verbose_name_plural = _("Счётчики нумерации документов")
        constraints = [
            models.UniqueConstraint(
                fields=["company", "doc_type", "period"], name="uniq_document_sequence_company_type_period"
            ),
        ]

    def save(self, *args, **kwargs):
        # Back-compat shim: rows created with only `year=` (legacy call sites, the 0037
        # backfill, admin) get their period derived from the calendar year, which is
        # exactly the yearly period key — so the default scheme keeps finding them.
        if not self.period and self.year is not None:
            self.period = str(self.year)
        super().save(*args, **kwargs)

    def __str__(self):
        scope = self.company_id or "platform"
        return f"[{scope}] {self.doc_type}-{self.period}: {self.last_value}"


class DocumentNumberingScheme(models.Model):
    """Configurable, per-company document numbering scheme (N1).

    Replaces the hardcoded `{prefix}-{label}-{year}-{NNNNN}` format with a token mask so
    a selling company can shape its own numbers (separator, padding, date tokens, reset
    period, start value). The number-minting CORE is untouched: the race-safe, no-gap
    `DocumentSequence` counter and the GLOBAL-UNIQUE safety (a company mints under its own
    counter ONLY when it carries a branding prefix; prefix-less companies share the
    platform counter/scheme) are preserved. See `crm/services/numbering.py`.

    ONE scheme per company (`company` OneToOne). `company=NULL` is the platform default
    scheme (seeded by migration to reproduce the historical format at zero visual diff);
    a company WITHOUT its own row falls back to it, and finally to the code-level default.

    Tokens supported in `pattern`:
      {prefix} — brand segment: rendered "<value>-" when the company prefix is non-empty,
                 "" otherwise (so both ACME-КП-2026-00001 and КП-2026-00001 are expressible)
      {type}   — human doc kind / label (КП, CT, INV, ACT, DOC)
      {YYYY}   — 4-digit calendar year        {YY} — 2-digit year
      {MM}     — 2-digit month
      {seq}    — the zero-padded sequential counter (MANDATORY — guarantees uniqueness)
    """

    RESET_NEVER = "never"
    RESET_YEARLY = "yearly"
    RESET_MONTHLY = "monthly"
    RESET_PERIOD_CHOICES = [
        (RESET_NEVER, _("Никогда")),
        (RESET_YEARLY, _("Ежегодно")),
        (RESET_MONTHLY, _("Ежемесячно")),
    ]

    # The code-level default = the historical hardcoded format (zero visual diff).
    DEFAULT_PATTERN = "{prefix}{type}-{YYYY}-{seq}"
    DEFAULT_PADDING = 5
    DEFAULT_RESET_PERIOD = RESET_YEARLY
    DEFAULT_START_VALUE = 0

    company = models.OneToOneField(
        "accounts.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="numbering_scheme",
        verbose_name=_("Компания"),
        help_text=_("Компания-владелец схемы; NULL — платформенная схема по умолчанию"),
    )
    pattern = models.CharField(
        max_length=128,
        default=DEFAULT_PATTERN,
        verbose_name=_("Маска номера"),
        help_text=_("Токены: {prefix} {type} {YYYY} {YY} {MM} {seq}. Обязателен {seq}."),
    )
    padding = models.PositiveSmallIntegerField(
        default=DEFAULT_PADDING,
        validators=[MinValueValidator(1)],
        verbose_name=_("Ширина счётчика"),
        help_text=_("Сколько цифр в {seq} с ведущими нулями (напр. 5 → 00001)"),
    )
    reset_period = models.CharField(
        max_length=16,
        choices=RESET_PERIOD_CHOICES,
        default=DEFAULT_RESET_PERIOD,
        verbose_name=_("Период сброса"),
        help_text=_("Когда счётчик обнуляется: никогда / ежегодно / ежемесячно"),
    )
    start_value = models.PositiveIntegerField(
        default=DEFAULT_START_VALUE,
        verbose_name=_("Стартовое значение"),
        help_text=_("Первый номер = start_value + 1 (по умолчанию 0 → первый номер 1)"),
    )
    type_labels = models.JSONField(
        default=default_type_labels,
        verbose_name=_("Метки типов документов"),
        help_text=_(
            "Что подставляется в токен {type} для каждого вида документа "
            "(КП / договор / инвойс / акт / произвольный) — редактируется компанией."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Создан"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Обновлён"))

    class Meta:
        verbose_name = _("Схема нумерации документов")
        verbose_name_plural = _("Схемы нумерации документов")

    def clean(self):
        pattern = (self.pattern or "").strip()
        if not pattern:
            raise ValidationError({"pattern": _("Маска номера не может быть пустой")})
        if "{seq}" not in pattern:
            # Without {seq} the same period would mint identical numbers → unique violation.
            raise ValidationError({"pattern": _("Маска обязана содержать токен {seq}")})
        labels = self.type_labels
        if not isinstance(labels, dict):
            raise ValidationError({"type_labels": _("Метки типов должны быть объектом код→метка")})
        for code in NUMBERING_TYPE_CODES:
            value = labels.get(code)
            if value is None:
                continue  # a missing key falls back to the shipped default at render time
            if not isinstance(value, str) or not value.strip():
                raise ValidationError({"type_labels": _("Метка типа не может быть пустой")})

    def __str__(self):
        scope = self.company_id or "platform"
        return f"[{scope}] {self.pattern}"
