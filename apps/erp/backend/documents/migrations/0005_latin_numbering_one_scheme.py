"""Нумерация латиницей и одна действующая схема (задача «Н», решение владельца 2026-11-13).

1. Обозначения, оставшиеся кириллическими умолчаниями (`КП`, `ДОГ`, `СЧ`, `АКТ`, `ДОК`), становятся латинскими
   умолчаниями; своё обозначение админа не трогается. Выданные номера и счётчики не меняются.
2. Компания без префикса нумерует по платформенной схеме (`company=NULL`), а редактор раньше сохранял её собственную
   строку, которая не применялась. Если платформенной строки нет, она создаётся из последней сохранённой схемы такой
   компании — настройки, сделанные в редакторе, начинают действовать.

Значения заморожены здесь: миграция не читает константы кода.
"""

from django.db import migrations

CYRILLIC = {"KP": "КП", "CT": "ДОГ", "INV": "СЧ", "ACT": "АКТ", "DOC": "ДОК"}
LATIN = {"KP": "QT", "CT": "CT", "INV": "INV", "ACT": "ACT", "DOC": "DOC"}


def forward(apps, schema_editor):
    Scheme = apps.get_model("documents", "DocumentNumberingScheme")
    Settings = apps.get_model("parties", "CompanySettings")
    for row in Scheme.objects.all():
        stored = dict(row.type_labels) if isinstance(row.type_labels, dict) else {}
        changed = {code: LATIN[code] for code, old in CYRILLIC.items() if stored.get(code, old) == old}
        if changed:
            row.type_labels = {**stored, **changed}
            row.save(update_fields=["type_labels"])

    if Scheme.objects.filter(company__isnull=True).exists():
        return
    prefixed = set(
        Settings.objects.exclude(doc_number_prefix__isnull=True)
        .exclude(doc_number_prefix="")
        .values_list("company_id", flat=True)
    )
    source = (
        Scheme.objects.filter(company__isnull=False)
        .exclude(company_id__in=prefixed)
        .order_by("-updated_at", "-id")
        .first()
    )
    if source is not None:
        Scheme.objects.create(
            company=None,
            pattern=source.pattern,
            padding=source.padding,
            reset_period=source.reset_period,
            start_value=source.start_value,
            type_labels=source.type_labels,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_spec_numbering_defaults"),
        ("parties", "0023_company_bank_accounts"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
