"""Виды шаблона для юридических документов + платформенный образец акта.

Rule 1 — справочные строки и заготовки приходят миграцией, а не хардкодом: после `migrate` на
чистой базе образец уже существует, и `get_or_create` в горячем пути не нужен.

Тело образца повторяет то, что акт печатал из кода, слово в слово: компания, которая ничего не
настраивала, обязана получить прежний документ. Структурные части вставлены плейсхолдерами
блоков — их вёрстку правит код, а не пользователь (аналог locked block у PandaDoc).
"""

from django.db import migrations

TEMPLATE_KINDS = [
    ("CONTRACT", "Договор", 40),
    ("INVOICE", "Счёт", 50),
    ("ACT", "Акт", 60),
]

ACT_SAMPLE_BODY = """
{{doc.refs}}
<p>Настоящий Акт составлен о том, что Поставщик передал, а Покупатель принял следующие
товары / услуги по указанной сделке:</p>
{{doc.items_table}}
{{doc.totals}}
<p>Услуги / товары оказаны / поставлены в полном объёме и в согласованные сроки. Стороны
претензий по объёму, качеству, комплектности и срокам друг к другу не имеют.</p>
""".strip()


def seed(apps, schema_editor):
    kind_model = apps.get_model("crm", "DocumentTemplateKind")
    template_model = apps.get_model("crm", "DocumentTemplate")
    for code, name, sort_order in TEMPLATE_KINDS:
        kind_model.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": sort_order, "is_active": True}
        )
    act_kind = kind_model.objects.get(code="ACT")
    template_model.objects.get_or_create(
        company=None,
        kind=act_kind,
        is_sample=True,
        defaults={
            "name": "Акт приёма-передачи (образец платформы)",
            "body_html": ACT_SAMPLE_BODY,
            "placeholders_used": ["doc.refs", "doc.items_table", "doc.totals"],
            "is_active": True,
        },
    )


def unseed(apps, schema_editor):
    """Обратная операция чистит только то, что создала: чужие шаблоны компаний не трогаем."""
    kind_model = apps.get_model("crm", "DocumentTemplateKind")
    template_model = apps.get_model("crm", "DocumentTemplate")
    template_model.objects.filter(company__isnull=True, is_sample=True, kind__code="ACT").delete()
    kind_model.objects.filter(code__in=[code for code, _, _ in TEMPLATE_KINDS]).delete()


class Migration(migrations.Migration):
    dependencies = [("crm", "0083_act_cancellation_and_reminder")]
    operations = [migrations.RunPython(seed, unseed)]
