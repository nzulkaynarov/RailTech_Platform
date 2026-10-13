"""D2a/D2b — виды шаблона «Квитанция об оплате» и «Накладная на отгрузку» + образцы.

Паттерн «регистр + печатный артефакт» (spec-d2-payments-shipments-registry-2026-08-01):
платёж и отгрузка остаются записями регистра, в документооборот попадает их печатный
артефакт. Rule 1 — образцы приходят миграцией; структурные части — плейсхолдерами блоков
(механика E1), компания без своего шаблона печатает платформенный образец.
"""

from django.db import migrations

TEMPLATE_KINDS = [
    ("RECEIPT", "Квитанция об оплате", 70),
    ("DELIVERY_NOTE", "Накладная на отгрузку", 80),
]

RECEIPT_BODY = """
{{doc.refs}}
<p>Настоящим подтверждается получение оплаты по счёту в размере {{doc.total}}
({{doc.total_words}}) — {{doc.payment_method}}, дата платежа {{doc.date}}.</p>
<p>Оплачено по счёту всего: {{doc.invoice_paid}}. Остаток к оплате: {{doc.invoice_balance}}.</p>
<p>Благодарим за своевременную оплату.</p>
{{doc.signatures}}
""".strip()

DELIVERY_NOTE_BODY = """
{{doc.refs}}
<p>Груз передан перевозчику{{doc.carrier_phrase}} для доставки Покупателю по указанной
сделке. Состав отправления:</p>
{{doc.items_table}}
<p>Получатель подтверждает приёмку груза по количеству мест при получении; приёмка по
качеству — по акту приёма-передачи.</p>
{{doc.signatures}}
""".strip()

SAMPLES = [
    ("RECEIPT", "Квитанция об оплате (образец платформы)", RECEIPT_BODY),
    ("DELIVERY_NOTE", "Накладная на отгрузку (образец платформы)", DELIVERY_NOTE_BODY),
]


def seed(apps, schema_editor):
    from crm.services.document_placeholders import extract_placeholders

    kind_model = apps.get_model("crm", "DocumentTemplateKind")
    template_model = apps.get_model("crm", "DocumentTemplate")
    for code, name, sort_order in TEMPLATE_KINDS:
        kind_model.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": sort_order, "is_active": True}
        )
    for code, name, body in SAMPLES:
        template_model.objects.get_or_create(
            company=None,
            kind=kind_model.objects.get(code=code),
            is_sample=True,
            defaults={
                "name": name,
                "body_html": body,
                "placeholders_used": extract_placeholders(body),
                "is_active": True,
            },
        )


def unseed(apps, schema_editor):
    """Чистит только созданное: чужие шаблоны компаний не трогаем."""
    kind_model = apps.get_model("crm", "DocumentTemplateKind")
    template_model = apps.get_model("crm", "DocumentTemplate")
    template_model.objects.filter(
        company__isnull=True, is_sample=True, kind__code__in=[c for c, _, _ in TEMPLATE_KINDS]
    ).delete()
    kind_model.objects.filter(code__in=[c for c, _, _ in TEMPLATE_KINDS]).delete()


class Migration(migrations.Migration):
    dependencies = [("crm", "0089_d2_receipt_delivery_note")]
    operations = [migrations.RunPython(seed, unseed)]
