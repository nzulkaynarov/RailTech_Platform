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
    """

    doc_type = models.CharField(max_length=16, verbose_name=_("Тип документа"))
    year = models.PositiveIntegerField(verbose_name=_("Год"))
    last_value = models.PositiveIntegerField(default=0, verbose_name=_("Последний номер"))

    class Meta:
        verbose_name = _("Счётчик нумерации документов")
        verbose_name_plural = _("Счётчики нумерации документов")
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "year"], name="uniq_document_sequence_type_year"),
        ]

    def __str__(self):
        return f"{self.doc_type}-{self.year}: {self.last_value}"
