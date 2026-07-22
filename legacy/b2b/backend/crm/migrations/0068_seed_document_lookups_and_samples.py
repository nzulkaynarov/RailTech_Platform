"""Seed «Документы 2.0» lookups + 5 platform sample templates (IRON RULE 1).

Lookup rows mirror crm/constants.py (DocumentTemplateKindCode /
GeneratedDocumentStatusCode). Sample templates are company-less (company=NULL,
is_sample=True) starting points a company copies to itself. Bodies use the flat
`{{placeholder}}` whitelist — NO template-engine syntax.
"""

from django.db import migrations

TEMPLATE_KINDS = [
    ("LETTER", "Письмо", 10),
    ("REPORT", "Рапорт / отчёт", 20),
    ("CUSTOM", "Произвольный", 30),
]
DOCUMENT_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("ISSUED", "Выпущен", 20),
    ("CANCELLED", "Отменён", 30),
]

# (name, kind_code, body_html). Flat {{placeholder}} tokens only.
SAMPLE_TEMPLATES = [
    (
        "Гарантийное письмо",
        "LETTER",
        "<h3>Гарантийное письмо</h3>"
        "<p>Настоящим {{company.name}} (ИНН {{company.inn}}) гарантирует оплату по "
        "сделке {{deal.number}} в полном объёме в согласованные сроки.</p>"
        "<p>Сумма обязательств соответствует коммерческому предложению {{quote.number}} "
        "на сумму {{quote.total}}.</p>"
        "<p>Дата: {{today}}</p>"
        "<p>{{user.full_name}}<br>{{company.name}}</p>",
    ),
    (
        "Сопроводительное письмо",
        "LETTER",
        "<h3>Сопроводительное письмо</h3>"
        "<p>Уважаемый(ая) {{counterparty.name}}!</p>"
        "<p>Направляем Вам комплект документов по сделке {{deal.number}} "
        "«{{deal.title}}». Просим рассмотреть и подтвердить получение.</p>"
        "<p>С уважением,<br>{{user.full_name}}<br>{{company.name}}</p>"
        "<p>{{today}}</p>",
    ),
    (
        "Доверенность",
        "CUSTOM",
        "<h3>Доверенность</h3>"
        "<p>{{company.name}} (ИНН {{company.inn}}, адрес: {{company.address}}) "
        "настоящей доверенностью уполномочивает {{user.full_name}} представлять "
        "интересы организации по сделке {{deal.number}}.</p>"
        "<p>Доверенность выдана {{today}} и действительна в течение календарного года.</p>"
        "<p>Руководитель: ______________________ / {{company.name}}</p>",
    ),
    (
        "Претензия",
        "LETTER",
        "<h3>Претензия</h3>"
        "<p>Кому: {{counterparty.name}} (ИНН {{counterparty.inn}})</p>"
        "<p>От: {{company.name}} (ИНН {{company.inn}})</p>"
        "<p>В рамках сделки {{deal.number}} по договору {{contract.number}} "
        "нами выявлено неисполнение обязательств. Требуем устранить нарушения "
        "в разумный срок.</p>"
        "<p>Дата: {{today}}<br>{{user.full_name}}</p>",
    ),
    (
        "Рапорт",
        "REPORT",
        "<h3>Рапорт</h3>"
        "<p>Составлен: {{today}}</p>"
        "<p>Ответственный: {{user.full_name}} ({{company.name}})</p>"
        "<p>По сделке {{deal.number}} «{{deal.title}}» докладываю о текущем "
        "статусе выполнения работ и предпринятых действиях.</p>"
        "<ul><li>Контрагент: {{counterparty.name}}</li>"
        "<li>КП: {{quote.number}} на сумму {{quote.total}}</li></ul>",
    ),
]


def _seed(apps, schema_editor):
    for model_name, rows in [
        ("DocumentTemplateKind", TEMPLATE_KINDS),
        ("GeneratedDocumentStatus", DOCUMENT_STATUSES),
    ]:
        model = apps.get_model("crm", model_name)
        for code, name, sort_order in rows:
            model.objects.get_or_create(
                code=code, defaults={"name": name, "sort_order": sort_order, "is_active": True}
            )

    kind_model = apps.get_model("crm", "DocumentTemplateKind")
    template_model = apps.get_model("crm", "DocumentTemplate")
    kinds = {row.code: row for row in kind_model.objects.all()}
    for name, kind_code, body_html in SAMPLE_TEMPLATES:
        placeholders = _extract(body_html)
        template_model.objects.get_or_create(
            company=None,
            name=name,
            is_sample=True,
            defaults={
                "kind": kinds[kind_code],
                "body_html": body_html,
                "placeholders_used": placeholders,
                "is_active": True,
            },
        )


def _extract(body_html):
    import re

    seen = []
    for match in re.finditer(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}", body_html):
        code = match.group(1).strip()
        if code not in seen:
            seen.append(code)
    return seen


def _unseed(apps, schema_editor):
    # Reverse no-op: lookup + sample rows are data; table removal handles teardown.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0067_documenttemplatekind_generateddocumentstatus_and_more"),
    ]

    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
