from django.db import models
from django.utils.translation import gettext_lazy as _


class DocumentSequence(models.Model):
    """Race-safe, gap-free, per-year document numbering counter.

    Replaces the `Model.objects.filter(year=...).count() + 1` pattern, which
    races under concurrency: two requests read the same count and mint the same
    number → IntegrityError (the `number` unique constraint) → a 500. One row
    per (doc_type, year); `next_value()` locks it with select_for_update so
    concurrent callers serialize and each gets a distinct, sequential number.

    doc_type is a short code: "INV" (invoice), "ACT", "CT" (contract).

    Per-company numbering: `company` scopes the counter so each selling company keeps
    its OWN gap-free sequence (ACME's contracts and BETA's contracts both start at
    00001 without colliding). company=NULL is the platform/legacy counter — existing
    rows keep it untouched. On Postgres a NULL is DISTINCT under a UniqueConstraint, so
    the platform path is NOT uniquely constrained across rows; that's intentional (only
    one NULL-company row per (doc_type, year) is ever created via select_for_update
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
    last_value = models.PositiveIntegerField(default=0, verbose_name=_("Последний номер"))

    class Meta:
        verbose_name = _("Счётчик нумерации документов")
        verbose_name_plural = _("Счётчики нумерации документов")
        constraints = [
            models.UniqueConstraint(
                fields=["company", "doc_type", "year"], name="uniq_document_sequence_company_type_year"
            ),
        ]

    def __str__(self):
        scope = self.company_id or "platform"
        return f"[{scope}] {self.doc_type}-{self.year}: {self.last_value}"
