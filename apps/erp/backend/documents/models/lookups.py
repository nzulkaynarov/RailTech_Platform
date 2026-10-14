from django.utils.translation import gettext_lazy as _

from core.models import AbstractLookup


class DocumentTemplateKind(AbstractLookup):
    """Вид шаблона документа. Seed: LETTER, REPORT, CUSTOM."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Вид шаблона документа")
        verbose_name_plural = _("Справочник: Виды шаблонов документов")


class GeneratedDocumentStatus(AbstractLookup):
    """Статус сгенерированного документа. Seed: DRAFT, ISSUED, CANCELLED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус документа")
        verbose_name_plural = _("Справочник: Статусы документов")


__all__ = [
    "DocumentTemplateKind",
    "GeneratedDocumentStatus",
]
