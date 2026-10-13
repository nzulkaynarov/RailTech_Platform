"""Платформенные образцы счёта и договора + починка образца акта (E1b).

Rule 1 — заготовки приходят миграцией: после `migrate` на чистой базе образцы уже существуют,
и компания без своего шаблона печатает прежний документ.

Тела образцов повторяют то, что документы печатали из кода. Структурные части (таблицы,
итоги, реквизиты, подписи) вставлены плейсхолдерами блоков — их вёрстку правит код, а не
пользователь (аналог locked block у PandaDoc). Формулировки D1 (`CompanyDocumentProfile`)
подставляются токенами `{{doc.contract_acceptance}}` и т.п. — настройки компании продолжают
питать платформенный образец (spec-editable-outgoing-documents §4).

Образец акта из 0084 чинится: он потерял блок подписей (акт без «М.П.» перестаёт быть
документом) и печатал платформенную оговорку вместо настроенной компанией (регресс D1).
Обновляется ТОЛЬКО нетронутое тело — правки платформенного администратора не перетираются.
"""

from django.db import migrations

ACT_BODY_0084 = """
{{doc.refs}}
<p>Настоящий Акт составлен о том, что Поставщик передал, а Покупатель принял следующие
товары / услуги по указанной сделке:</p>
{{doc.items_table}}
{{doc.totals}}
<p>Услуги / товары оказаны / поставлены в полном объёме и в согласованные сроки. Стороны
претензий по объёму, качеству, комплектности и срокам друг к другу не имеют.</p>
""".strip()

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

SAMPLES = [
    ("INVOICE", "Счёт на оплату (образец платформы)", INVOICE_BODY),
    ("CONTRACT", "Договор поставки (образец платформы)", CONTRACT_BODY),
]


def _placeholders(body: str) -> list:
    from crm.services.document_placeholders import extract_placeholders

    return extract_placeholders(body)


def seed(apps, schema_editor):
    kind_model = apps.get_model("crm", "DocumentTemplateKind")
    template_model = apps.get_model("crm", "DocumentTemplate")
    for code, name, body in SAMPLES:
        template_model.objects.get_or_create(
            company=None,
            kind=kind_model.objects.get(code=code),
            is_sample=True,
            defaults={
                "name": name,
                "body_html": body,
                "placeholders_used": _placeholders(body),
                "is_active": True,
            },
        )
    # Акт: подписи вернулись, оговорка снова слушает настройку компании (D1).
    template_model.objects.filter(
        company__isnull=True, is_sample=True, kind__code="ACT", body_html=ACT_BODY_0084
    ).update(body_html=ACT_BODY, placeholders_used=_placeholders(ACT_BODY))


def unseed(apps, schema_editor):
    """Обратная операция чистит только то, что создала: чужие шаблоны компаний не трогаем."""
    template_model = apps.get_model("crm", "DocumentTemplate")
    template_model.objects.filter(
        company__isnull=True, is_sample=True, kind__code__in=[code for code, _, _ in SAMPLES]
    ).delete()
    template_model.objects.filter(company__isnull=True, is_sample=True, kind__code="ACT", body_html=ACT_BODY).update(
        body_html=ACT_BODY_0084, placeholders_used=_placeholders(ACT_BODY_0084)
    )


class Migration(migrations.Migration):
    dependencies = [("crm", "0084_legal_template_kinds_and_act_sample")]
    operations = [migrations.RunPython(seed, unseed)]
