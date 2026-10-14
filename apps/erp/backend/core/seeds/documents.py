"""Documents lookups and sample templates seed."""

import re

TEMPLATE_KINDS = [
    ("LETTER", "Письмо", 10),
    ("REPORT", "Рапорт / отчёт", 20),
    ("CUSTOM", "Произвольный", 30),
    ("CONTRACT", "Договор", 40),
    ("INVOICE", "Счёт", 50),
    ("ACT", "Акт", 60),
    ("RECEIPT", "Квитанция об оплате", 70),
    ("DELIVERY_NOTE", "Накладная на отгрузку", 80),
]

DOCUMENT_STATUSES = [
    ("DRAFT", "Черновик", 10),
    ("ISSUED", "Выпущен", 20),
    ("CANCELLED", "Отменён", 30),
]

ACT_BODY = """
{{doc.refs}}
<p>Настоящий Акт составлен о том, что Поставщик передал, а Покупатель принял следующие
товары / услуги по указанной сделке:</p>
{{doc.items_table}}
{{doc.totals}}
{{doc.act_closing}}
{{doc.signatures}}
""".strip()

INVOICE_BODY = """
{{doc.items_table}}
{{doc.totals}}
{{doc.payment_requisites}}
{{doc.notes}}
{{doc.signatures}}
""".strip()

CONTRACT_BODY = """
<p>г. Ташкент<span>{{doc.date}} г.</span></p>
<h2>1. Предмет договора</h2>
<p>Поставщик обязуется передать в собственность Покупателя, а Покупатель — принять и оплатить
товары (продукцию) в соответствии со Спецификацией (Приложение № 1), являющейся неотъемлемой
частью настоящего Договора.</p>
{{doc.spec_table}}
{{doc.totals}}
<h2>2. Цена и порядок расчётов</h2>
<p>Общая сумма Договора составляет {{doc.total}}, включая НДС по ставке {{doc.vat_rate}}%.
Цены указаны в {{doc.currency}}. Расчёты производятся в безналичной форме на банковский счёт
Поставщика, указанный в разделе «Реквизиты сторон», в порядке и в сроки, согласованные
Сторонами. Обязательство по оплате считается исполненным с момента поступления денежных
средств на счёт Поставщика.</p>
<h2>3. Сроки и условия поставки</h2>
<p>Поставка осуществляется {{doc.delivery_terms}}. Право собственности на товар и риск
случайной гибели переходят к Покупателю в момент передачи товара Покупателю
(грузоперевозчику).</p>
<h2>4. Качество, комплектность и приёмка</h2>
{{doc.contract_acceptance}}
<h2>5. Ответственность сторон</h2>
{{doc.contract_liability}}
<h2>6. Обстоятельства непреодолимой силы (форс-мажор)</h2>
<p>Стороны освобождаются от ответственности за частичное или полное неисполнение обязательств,
если оно явилось следствием обстоятельств непреодолимой силы, возникших после заключения
Договора. Сторона, для которой создалась невозможность исполнения, обязана известить другую
Сторону в течение разумного срока.</p>
<h2>7. Порядок разрешения споров и применимое право</h2>
<p>Все споры и разногласия решаются путём переговоров. При недостижении согласия спор
передаётся на рассмотрение суда по месту нахождения ответчика в соответствии с
законодательством Республики Узбекистан, которое является применимым правом по настоящему
Договору.</p>
<h2>8. Срок действия договора</h2>
<p>Договор вступает в силу {{doc.valid_from}} и действует {{doc.valid_until}}.</p>
<h2>9. Заключительные положения</h2>
<p>Договор составлен в двух экземплярах, имеющих равную юридическую силу, по одному для каждой
из Сторон. Все изменения и дополнения действительны при их совершении в письменной форме.
Стороны признают юридическую силу документов, подписанных простой электронной подписью в
рамках согласованного электронного документооборота.</p>
{{doc.extra_terms_article}}
{{doc.notes}}
{{doc.requisites_and_signatures}}
""".strip()

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
    ("Акт приёма-передачи (образец платформы)", "ACT", ACT_BODY),
    ("Счёт на оплату (образец платформы)", "INVOICE", INVOICE_BODY),
    ("Договор поставки (образец платформы)", "CONTRACT", CONTRACT_BODY),
    ("Квитанция об оплате (образец платформы)", "RECEIPT", RECEIPT_BODY),
    ("Накладная на отгрузку (образец платформы)", "DELIVERY_NOTE", DELIVERY_NOTE_BODY),
]


def extract_placeholders(body_html: str) -> list[str]:
    seen = []
    for match in re.finditer(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}", body_html):
        code = match.group(1).strip()
        if code not in seen:
            seen.append(code)
    return seen


def seed_document_lookups_and_samples(apps=None, schema_editor=None):
    if apps is None:
        from django.apps import apps as django_apps

        apps = django_apps

    try:
        DocumentTemplateKind = apps.get_model("documents", "DocumentTemplateKind")
        GeneratedDocumentStatus = apps.get_model("documents", "GeneratedDocumentStatus")
        DocumentTemplate = apps.get_model("documents", "DocumentTemplate")
    except LookupError:
        DocumentTemplateKind = apps.get_model("crm", "DocumentTemplateKind")
        GeneratedDocumentStatus = apps.get_model("crm", "GeneratedDocumentStatus")
        DocumentTemplate = apps.get_model("crm", "DocumentTemplate")

    for code, name, sort_order in TEMPLATE_KINDS:
        DocumentTemplateKind.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": sort_order, "is_active": True}
        )

    for code, name, sort_order in DOCUMENT_STATUSES:
        GeneratedDocumentStatus.objects.get_or_create(
            code=code, defaults={"name": name, "sort_order": sort_order, "is_active": True}
        )

    kinds = {k.code: k for k in DocumentTemplateKind.objects.all()}
    for name, kind_code, body_html in SAMPLE_TEMPLATES:
        kind = kinds.get(kind_code)
        if not kind:
            continue
        placeholders = extract_placeholders(body_html)
        DocumentTemplate.objects.get_or_create(
            company=None,
            name=name,
            is_sample=True,
            defaults={
                "kind": kind,
                "body_html": body_html,
                "placeholders_used": placeholders,
                "is_active": True,
            },
        )
