"""ДОК-13: убрать из библиотеки шаблонов то, что нельзя применить (решение владельца 2026-11-20).

Пять образцов («Гарантийное письмо», «Сопроводительное письмо», «Претензия», «Рапорт», «Доверенность») и виды «Письмо»,
«Рапорт», «Произвольный». Письма теперь — шаблоны на бланке в документообороте.

Безопасно для данных: образец, на который ссылается выпущенный документ, не удаляется, а снимается с показа
(`is_active=False`; библиотека не отдаёт неактивные образцы). Вид, на который ссылается любой шаблон, тоже только
снимается с показа; без ссылок — удаляется. Шаблоны компаний не трогаются. Имена и коды заморожены здесь.
"""

from django.db import migrations

SAMPLE_NAMES = ["Гарантийное письмо", "Сопроводительное письмо", "Претензия", "Рапорт", "Доверенность"]
RETIRED_KINDS = ["LETTER", "REPORT", "CUSTOM"]


def forward(apps, schema_editor):
    Template = apps.get_model("documents", "DocumentTemplate")
    Kind = apps.get_model("documents", "DocumentTemplateKind")
    Generated = apps.get_model("documents", "GeneratedDocument")

    samples = Template.objects.filter(company__isnull=True, is_sample=True, name__in=SAMPLE_NAMES)
    used = set(Generated.objects.filter(template__in=samples).values_list("template_id", flat=True))
    samples.exclude(pk__in=used).delete()
    samples.filter(pk__in=used).update(is_active=False)

    for kind in Kind.objects.filter(code__in=RETIRED_KINDS):
        if Template.objects.filter(kind=kind).exists():
            if kind.is_active:
                kind.is_active = False
                kind.save(update_fields=["is_active"])
        else:
            kind.delete()


class Migration(migrations.Migration):
    dependencies = [("documents", "0005_latin_numbering_one_scheme")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
