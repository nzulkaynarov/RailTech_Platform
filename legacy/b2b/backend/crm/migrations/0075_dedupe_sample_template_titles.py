"""D0 — drop the duplicate title heading from the 5 platform sample template bodies.

Root cause the wave closes: the branded wrapper (crm/generated_document_pdf.html →
crm/_document_base.html) ALREADY prints the document title as the letterhead H1
(`doc_title` = `document.title`). Each sample body ALSO opened with `<h3>Гарантийное
письмо</h3>` etc., so the rendered PDF showed the title TWICE (audit «заголовок ×2»).
This migration removes the leading heading — the letterhead H1 is the single canonical
title, the body is pure content (consistent with КП / договор / инвойс). Re-sanitised +
placeholders recomputed. Reverse restores the pre-D0 bodies (0072 state, with the heading).
"""

from django.db import migrations

# (name, new body_html) — leading duplicate <h3>Title</h3> removed; substance unchanged.
NEW_BODIES = {
    "Гарантийное письмо": (
        "<p>Настоящим гарантируем оплату по сделке {{deal.number}} в полном объёме "
        "в согласованные сроки.</p>"
        "<p>Сумма обязательств соответствует коммерческому предложению {{quote.number}} "
        "на сумму {{quote.total}}.</p>"
        "<p>Дата: {{today}}</p>"
        "<p>{{user.full_name}}</p>"
    ),
    "Сопроводительное письмо": (
        "<p>Уважаемый(ая) {{counterparty.name}}!</p>"
        "<p>Направляем Вам комплект документов по сделке {{deal.number}} "
        "«{{deal.title}}». Просим рассмотреть и подтвердить получение.</p>"
        "<p>С уважением,<br>{{user.full_name}}</p>"
        "<p>{{today}}</p>"
    ),
    "Доверенность": (
        "<p>Настоящей доверенностью уполномочиваем {{user.full_name}} представлять "
        "интересы нашей организации по сделке {{deal.number}}.</p>"
        "<p>Доверенность выдана {{today}} и действительна в течение календарного года.</p>"
        "<p>Руководитель: ______________________</p>"
    ),
    "Претензия": (
        "<p>Кому: {{counterparty.name}} (ИНН {{counterparty.inn}})</p>"
        "<p>В рамках сделки {{deal.number}} по договору {{contract.number}} "
        "нами выявлено неисполнение обязательств. Требуем устранить нарушения "
        "в разумный срок.</p>"
        "<p>Дата: {{today}}<br>{{user.full_name}}</p>"
    ),
    "Рапорт": (
        "<p>Составлен: {{today}}</p>"
        "<p>Ответственный: {{user.full_name}}</p>"
        "<p>По сделке {{deal.number}} «{{deal.title}}» докладываю о текущем "
        "статусе выполнения работ и предпринятых действиях.</p>"
        "<ul><li>Контрагент: {{counterparty.name}}</li>"
        "<li>КП: {{quote.number}} на сумму {{quote.total}}</li></ul>"
    ),
}

# The 0072 bodies (with the leading <h3> heading) — restored verbatim on reverse.
OLD_BODIES = {
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


def _apply(bodies):
    """Return a RunPython fn that rewrites each sample body (sanitised + placeholders recomputed)."""

    def _run(apps, schema_editor):
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
        ("crm", "0074_documentnumberingscheme_type_labels"),
    ]

    operations = [
        migrations.RunPython(_apply(NEW_BODIES), _apply(OLD_BODIES)),
    ]
