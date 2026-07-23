"""T1-b — declutter the 5 platform sample template bodies (spec-numbering-templater, wave T1).

Root cause the wave closes: the branded document wrapper (crm/_document_base.html) ALREADY prints
the owner company's шапка (лого + название + ИНН + адрес) and подвал. The original sample bodies
ALSO carried `{{company.name}}` / `{{company.inn}}` / `{{company.address}}` — so the rendered PDF
repeated the same requisites twice. This migration rewrites each sample body to the SUBSTANCE of the
letter (contract/deal/quote/counterparty dynamics + signatory), dropping the owner-company requisites
that the letterhead owns. Re-sanitised (allowlist) + placeholders recomputed. Reverse restores the
pre-T1 bodies verbatim (0068 seed).
"""

from django.db import migrations

# (name, new body_html) — owner-company requisites removed; only dynamic placeholders remain.
NEW_BODIES = {
    "Гарантийное письмо": (
        "<h3>Гарантийное письмо</h3>"
        "<p>Настоящим гарантируем оплату по сделке {{deal.number}} в полном объёме "
        "в согласованные сроки.</p>"
        "<p>Сумма обязательств соответствует коммерческому предложению {{quote.number}} "
        "на сумму {{quote.total}}.</p>"
        "<p>Дата: {{today}}</p>"
        "<p>{{user.full_name}}</p>"
    ),
    "Сопроводительное письмо": (
        "<h3>Сопроводительное письмо</h3>"
        "<p>Уважаемый(ая) {{counterparty.name}}!</p>"
        "<p>Направляем Вам комплект документов по сделке {{deal.number}} "
        "«{{deal.title}}». Просим рассмотреть и подтвердить получение.</p>"
        "<p>С уважением,<br>{{user.full_name}}</p>"
        "<p>{{today}}</p>"
    ),
    "Доверенность": (
        "<h3>Доверенность</h3>"
        "<p>Настоящей доверенностью уполномочиваем {{user.full_name}} представлять "
        "интересы нашей организации по сделке {{deal.number}}.</p>"
        "<p>Доверенность выдана {{today}} и действительна в течение календарного года.</p>"
        "<p>Руководитель: ______________________</p>"
    ),
    "Претензия": (
        "<h3>Претензия</h3>"
        "<p>Кому: {{counterparty.name}} (ИНН {{counterparty.inn}})</p>"
        "<p>В рамках сделки {{deal.number}} по договору {{contract.number}} "
        "нами выявлено неисполнение обязательств. Требуем устранить нарушения "
        "в разумный срок.</p>"
        "<p>Дата: {{today}}<br>{{user.full_name}}</p>"
    ),
    "Рапорт": (
        "<h3>Рапорт</h3>"
        "<p>Составлен: {{today}}</p>"
        "<p>Ответственный: {{user.full_name}}</p>"
        "<p>По сделке {{deal.number}} «{{deal.title}}» докладываю о текущем "
        "статусе выполнения работ и предпринятых действиях.</p>"
        "<ul><li>Контрагент: {{counterparty.name}}</li>"
        "<li>КП: {{quote.number}} на сумму {{quote.total}}</li></ul>"
    ),
}

# The pre-T1 bodies (0068 seed) — restored verbatim on reverse.
OLD_BODIES = {
    "Гарантийное письмо": (
        "<h3>Гарантийное письмо</h3>"
        "<p>Настоящим {{company.name}} (ИНН {{company.inn}}) гарантирует оплату по "
        "сделке {{deal.number}} в полном объёме в согласованные сроки.</p>"
        "<p>Сумма обязательств соответствует коммерческому предложению {{quote.number}} "
        "на сумму {{quote.total}}.</p>"
        "<p>Дата: {{today}}</p>"
        "<p>{{user.full_name}}<br>{{company.name}}</p>"
    ),
    "Сопроводительное письмо": (
        "<h3>Сопроводительное письмо</h3>"
        "<p>Уважаемый(ая) {{counterparty.name}}!</p>"
        "<p>Направляем Вам комплект документов по сделке {{deal.number}} "
        "«{{deal.title}}». Просим рассмотреть и подтвердить получение.</p>"
        "<p>С уважением,<br>{{user.full_name}}<br>{{company.name}}</p>"
        "<p>{{today}}</p>"
    ),
    "Доверенность": (
        "<h3>Доверенность</h3>"
        "<p>{{company.name}} (ИНН {{company.inn}}, адрес: {{company.address}}) "
        "настоящей доверенностью уполномочивает {{user.full_name}} представлять "
        "интересы организации по сделке {{deal.number}}.</p>"
        "<p>Доверенность выдана {{today}} и действительна в течение календарного года.</p>"
        "<p>Руководитель: ______________________ / {{company.name}}</p>"
    ),
    "Претензия": (
        "<h3>Претензия</h3>"
        "<p>Кому: {{counterparty.name}} (ИНН {{counterparty.inn}})</p>"
        "<p>От: {{company.name}} (ИНН {{company.inn}})</p>"
        "<p>В рамках сделки {{deal.number}} по договору {{contract.number}} "
        "нами выявлено неисполнение обязательств. Требуем устранить нарушения "
        "в разумный срок.</p>"
        "<p>Дата: {{today}}<br>{{user.full_name}}</p>"
    ),
    "Рапорт": (
        "<h3>Рапорт</h3>"
        "<p>Составлен: {{today}}</p>"
        "<p>Ответственный: {{user.full_name}} ({{company.name}})</p>"
        "<p>По сделке {{deal.number}} «{{deal.title}}» докладываю о текущем "
        "статусе выполнения работ и предпринятых действиях.</p>"
        "<ul><li>Контрагент: {{counterparty.name}}</li>"
        "<li>КП: {{quote.number}} на сумму {{quote.total}}</li></ul>"
    ),
}


def _apply(bodies):
    """Return a RunPython fn that rewrites each sample body (sanitised + placeholders recomputed)."""

    def _run(apps, schema_editor):
        # Pure, model-free helpers — safe to import at run time (no ORM coupling).
        from crm.services.document_placeholders import extract_placeholders, sanitize_template_html

        template_model = apps.get_model("crm", "DocumentTemplate")
        for name, body_html in bodies.items():
            clean = sanitize_template_html(body_html)
            template_model.objects.filter(company__isnull=True, is_sample=True, name=name).update(
                body_html=clean, placeholders_used=extract_placeholders(clean)
            )

    return _run


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0071_generateddocument_brand_snapshot"),
    ]

    operations = [
        migrations.RunPython(_apply(NEW_BODIES), _apply(OLD_BODIES)),
    ]
