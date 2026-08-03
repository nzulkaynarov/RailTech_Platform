"""Структурные блоки документа как плейсхолдеры.

Зачем так. Компания должна иметь возможность править ТЕКСТ документа — этого требует любая
реальная сделка, где юрист контрагента возражает по формулировке. Но таблица позиций, блок
итогов и ссылки на сделку/договор/счёт — не текст, а данные с обязательной формой: если дать
править их свободным HTML, документ перестанет быть документом.

Эталон решает это блоками с замком (PandaDoc: «restrict editing» + «lock block position»,
снять может только администратор). Блочного редактора у нас нет, поэтому замок выражен иначе:
**блок вставляется в шаблон ОДНИМ плейсхолдером**. Компания решает, где блок стоит и какой
текст его окружает, но не то, что у него внутри. Это тот же контракт, что у PandaDoc, только
записанный токеном, а не свойством блока.

Формулировки D1 (`CompanyDocumentProfile.*_text`) подставляются в ПЛАТФОРМЕННЫЕ образцы теми
же токенами (spec-editable-outgoing-documents §4): пока компания не завела свой шаблон, её
настройки формулировок продолжают питать документ; свой шаблон — компания пишет текст прямо.
"""

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from .fulfillment import delivery_note_number

#: Токен → человеческая подпись. Каталог один: и редактор показывает его пользователю, и
#: проверка целостности (E2) сверяется с ним, поэтому разъехаться они не могут.
DOCUMENT_BLOCKS = {
    "doc.refs": "Блок: ссылки на сделку, договор и счёт",
    "doc.items_table": "Блок: таблица позиций",
    "doc.totals": "Блок: итоги и НДС",
    "doc.signatures": "Блок: подписи сторон",
    "doc.payment_requisites": "Блок: платёжные реквизиты",
    "doc.spec_table": "Блок: спецификация (Приложение № 1)",
    "doc.requisites_and_signatures": "Блок: реквизиты и подписи Сторон",
    "doc.notes": "Блок: примечание документа",
    "doc.extra_terms_article": "Блок: особые условия (настройка «Формулировки»)",
}

#: Формулировки компании (D1): токен → поле CompanyDocumentProfile. Пустое поле = платформенный
#: текст по умолчанию (crm.document_wording), а не пустое место в документе.
DOCUMENT_WORDING_TOKENS = {
    "doc.act_closing": "act_closing_text",
    "doc.contract_acceptance": "contract_acceptance_text",
    "doc.contract_liability": "contract_liability_text",
}

#: E2 — проверка целостности вместо блочных замков: без этих блоков документ перестаёт быть
#: документом (счёт без реквизитов нельзя оплатить, договор без подписей нельзя заключить).
#: Активировать шаблон юридического вида без них нельзя; правится ТЕКСТ вокруг, не состав.
REQUIRED_TEMPLATE_BLOCKS = {
    "ACT": ("doc.items_table", "doc.totals", "doc.signatures"),
    "INVOICE": ("doc.items_table", "doc.totals", "doc.payment_requisites"),
    "CONTRACT": ("doc.spec_table", "doc.totals", "doc.requisites_and_signatures"),
}


def missing_required_blocks(kind_code: str, body_html: str) -> list:
    """Каких обязательных блоков не хватает телу шаблона этого вида (пусто = целостно).

    Один источник правды с каталогом DOCUMENT_BLOCKS: редактор показывает блоки, эта проверка
    требует их — разъехаться они не могут.
    """
    from .document_placeholders import extract_placeholders

    required = REQUIRED_TEMPLATE_BLOCKS.get(kind_code)
    if not required:
        return []
    present = set(extract_placeholders(body_html or ""))
    return [token for token in required if token not in present]


#: Скалярные значения юридического документа.
DOCUMENT_SCALARS = {
    "doc.number": "Номер документа",
    "doc.date": "Дата документа",
    "doc.total": "Сумма документа",
    "doc.currency": "Валюта документа",
    "doc.vat_rate": "Ставка НДС, %",
    "doc.delivery_terms": "Условия поставки (фраза)",
    "doc.valid_from": "Начало действия договора (фраза)",
    "doc.valid_until": "Окончание действия договора (фраза)",
}


def preview_block_stubs() -> dict:
    """Заглушки для предпросмотра редактора шаблонов.

    Настоящие блоки сервер собирает только при печати документа (им нужны сделка, счёт,
    договор). В превью на месте токена показывается подписанная метка — автор видит, ГДЕ
    встанет блок, и токен не пугает предупреждением «неизвестный плейсхолдер».
    """
    from django.utils.html import escape

    wording_stub = "Формулировка компании (настройка «Формулировки»)"
    labels = {
        **DOCUMENT_BLOCKS,
        **{code: wording_stub for code in DOCUMENT_WORDING_TOKENS},
        **DOCUMENT_SCALARS,
    }
    return {
        code: mark_safe(
            '<span style="display:inline-block;border:1px dashed #9aa0a6;border-radius:3px;'
            f'padding:1px 6px;color:#7a828f;font-size:90%;">⟦ {escape(label)} ⟧</span>'
        )
        for code, label in labels.items()
    }


def _wording_html(seller_profile, field: str, selections=None):
    """Формулировка компании (или платформенная) как готовый HTML-блок.

    Значение — прозаический ТЕКСТ из профиля, поэтому он экранируется, и только потом
    размечается абзацами (`linebreaks`) — ровно то, что делал `|linebreaks` в код-шаблоне.
    """
    from django.template.defaultfilters import linebreaks
    from django.utils.html import escape

    from ..document_wording import resolve_wording_selected

    return mark_safe(linebreaks(escape(resolve_wording_selected(selections, seller_profile, field))))


def act_block_values(act, invoice, totals, ccy: str, *, seller=None, seller_profile=None) -> dict:
    """HTML блоков для акта. Разметка та же, что печаталась из кода, — вынесена в partials,
    чтобы у шаблона компании и у платформенного образца был ОДИН источник вёрстки."""
    return {
        "doc.refs": mark_safe(render_to_string("crm/blocks/_doc_refs.html", {"act": act, "invoice": invoice})),
        "doc.items_table": mark_safe(
            render_to_string(
                "crm/blocks/_items_table.html", {"items": invoice.items.all() if invoice else [], "ccy": ccy}
            )
        ),
        "doc.totals": mark_safe(render_to_string("crm/blocks/_totals.html", {"totals": totals})),
        "doc.act_closing": _wording_html(
            seller_profile, "act_closing_text", selections=getattr(act, "wording_selections", None)
        ),
        "doc.signatures": mark_safe(
            render_to_string(
                "crm/blocks/_signatures_act.html",
                {
                    "seller": seller,
                    "seller_profile": seller_profile,
                    "company": act.deal.company,
                    # Соло-сделка (Deal.company nullable): покупатель — офлайн-контакт.
                    "contact": getattr(act.deal, "contact", None),
                },
            )
        ),
    }


def invoice_block_values(invoice, items, totals, ccy: str, *, seller=None, seller_profile=None) -> dict:
    """HTML блоков для счёта: таблица позиций, итоги, платёжные реквизиты, примечание, подписи."""
    return {
        "doc.items_table": mark_safe(render_to_string("crm/blocks/_items_table.html", {"items": items, "ccy": ccy})),
        "doc.totals": mark_safe(render_to_string("crm/blocks/_totals.html", {"totals": totals})),
        "doc.payment_requisites": mark_safe(
            render_to_string(
                "crm/blocks/_payment_requisites.html",
                {"invoice": invoice, "seller": seller, "seller_profile": seller_profile, "ccy": ccy},
            )
        ),
        "doc.notes": mark_safe(
            render_to_string("crm/blocks/_notes.html", {"label": "Примечание", "text": invoice.notes})
        ),
        "doc.signatures": mark_safe(
            render_to_string("crm/blocks/_signatures_invoice.html", {"seller_profile": seller_profile})
        ),
    }


def contract_block_values(contract, items, totals, ccy: str, *, seller=None, seller_profile=None) -> dict:
    """HTML блоков для договора: спецификация, итоги, особые условия, реквизиты и подписи.

    «Особые условия» — условная статья: печатается только когда компания её написала (пустой
    пункт в договоре хуже отсутствующего). Номер статьи реквизитов сдвигается ровно на этот
    случай — как это делал код-шаблон, без «дыры» в нумерации.
    """
    from ..document_wording import resolve_wording_selected

    # E4: формулировки ЭТОГО договора (выбор менеджера + снапшот) важнее живого профиля.
    selections = getattr(contract, "wording_selections", None)
    extra_terms = resolve_wording_selected(selections, seller_profile, "contract_extra_terms_text")
    extra_article = ""
    if extra_terms.strip():
        extra_article = render_to_string(
            "crm/blocks/_extra_terms_article.html", {"heading": "10. Особые условия", "text": extra_terms}
        )
    requisites_no = "11" if extra_terms.strip() else "10"
    return {
        "doc.spec_table": mark_safe(render_to_string("crm/blocks/_spec_table.html", {"items": items, "ccy": ccy})),
        "doc.totals": mark_safe(render_to_string("crm/blocks/_totals.html", {"totals": totals})),
        "doc.contract_acceptance": _wording_html(seller_profile, "contract_acceptance_text", selections=selections),
        "doc.contract_liability": _wording_html(seller_profile, "contract_liability_text", selections=selections),
        "doc.extra_terms_article": mark_safe(extra_article),
        "doc.notes": mark_safe(
            render_to_string("crm/blocks/_notes.html", {"label": "Дополнительные условия", "text": contract.notes})
        ),
        "doc.requisites_and_signatures": mark_safe(
            render_to_string(
                "crm/blocks/_requisites_and_signatures.html",
                {
                    "contract": contract,
                    "seller": seller,
                    "seller_profile": seller_profile,
                    "company": contract.deal.company,
                    "article_no": requisites_no,
                },
            )
        ),
    }


def company_template_for(company, kind_code: str):
    """Активный шаблон компании этого вида, иначе платформенный образец, иначе None.

    Порядок — тот же, что у остальных настроек документа: своё важнее общего, а общее важнее
    пустоты. None означает «печатать из кода» — так ведут себя документы, для которых образец
    ещё не заведён.
    """
    from crm.models import DocumentTemplate

    if company is not None:
        own = (
            DocumentTemplate.objects.filter(company=company, kind__code=kind_code, is_active=True)
            .order_by("-updated_at")
            .first()
        )
        if own is not None:
            return own
    return DocumentTemplate.objects.filter(company__isnull=True, is_sample=True, kind__code=kind_code).first()


def frozen_body_for(supplier, kind_code: str) -> str:
    """Тело действующего шаблона — для заморозки в документ при выпуске (E3).

    Документ печатается по той редакции, что действовала на момент выпуска, и хранит её у
    себя: правка шаблона задним числом не переписывает выпущенные документы. Блоки при этом
    остаются живыми данными (штампы подписей, суммы) — замораживается только ТЕКСТ.
    """
    template = company_template_for(supplier, kind_code)
    return template.body_html if template is not None else ""


def render_document_body(body_html: str, *, blocks: dict, scalars: dict) -> str:
    """Подстановка блоков и скаляров в тело шаблона.

    Разница между ними — вопрос безопасности, а не удобства:

    * **скаляры** приходят из данных (номер, дата, сумма) и ЭКРАНИРУЮТСЯ — иначе значение с
      разметкой стало бы разметкой (XSS);
    * **блоки** сервер собрал сам из наших же partials, они уже HTML, и экранировать их значило
      бы напечатать теги буквально.

    Тело шаблона НЕ рендерится как Django-шаблон: подстановка строковая (нет SSTI), а сам
    `body_html` прошёл санитайзинг по allowlist при сохранении.
    """
    from django.utils.html import escape

    from .document_placeholders import PLACEHOLDER_RE

    def _sub(match) -> str:
        code = match.group(1).strip()
        if code in blocks:
            return str(blocks[code])
        if code in scalars:
            return escape("" if scalars[code] is None else str(scalars[code]))
        return match.group(0)

    return PLACEHOLDER_RE.sub(_sub, body_html or "")


def render_act_body(
    act, invoice, totals, ccy: str, template, *, seller=None, seller_profile=None, body_html=None
) -> str:
    """Тело акта по шаблону компании либо по платформенному образцу.

    `body_html` — замороженная при выпуске редакция (E3): когда она есть, живой шаблон не
    читается вовсе, и его правка не меняет уже выпущенный документ."""
    return render_document_body(
        body_html if body_html else template.body_html,
        blocks=act_block_values(act, invoice, totals, ccy, seller=seller, seller_profile=seller_profile),
        scalars={
            "doc.number": act.number,
            "doc.date": act.issued_at.strftime("%d.%m.%Y") if act.issued_at else "",
            "doc.total": act.total_amount,
        },
    )


def render_invoice_body(
    invoice, items, totals, ccy: str, template, *, seller=None, seller_profile=None, body_html=None
) -> str:
    """Тело счёта по шаблону компании либо по платформенному образцу (`body_html` — E3-снапшот)."""
    from crm.templatetags.document_format import money

    issued = invoice.issued_at or invoice.created_at
    return render_document_body(
        body_html if body_html else template.body_html,
        blocks=invoice_block_values(invoice, items, totals, ccy, seller=seller, seller_profile=seller_profile),
        scalars={
            "doc.number": invoice.number,
            "doc.date": issued.strftime("%d.%m.%Y") if issued else "",
            "doc.total": money(invoice.total_incl_vat, ccy),
            "doc.currency": ccy,
        },
    )


def _contract_delivery_terms(quote) -> str:
    """Фраза статьи 3 — та же логика ветвления, что была в код-шаблоне."""
    lead = getattr(quote, "effective_delivery_lead_time_days", None) if quote is not None else None
    if lead:
        phrase = f"в срок до {lead} календарных дней с момента возникновения обязательства по поставке"
    else:
        phrase = "в сроки, согласованные Сторонами"
    basis = getattr(quote, "delivery_basis", None) if quote is not None else None
    if basis is not None:
        phrase += f" на условиях поставки {basis.code}"
        if basis.name:
            phrase += f" ({basis.name})"
    return phrase


def render_contract_body(
    contract, items, totals, ccy: str, template, *, seller=None, seller_profile=None, body_html=None
) -> str:
    """Тело договора по шаблону компании либо по платформенному образцу (`body_html` — E3-снапшот)."""
    from crm.templatetags.document_format import money

    quote = contract.quote if contract.quote_id else None
    vat_rate = getattr(quote, "vat_rate", None) if quote is not None else None
    valid_from = (
        f"с {contract.valid_from.strftime('%d.%m.%Y')}"
        if contract.valid_from
        else "с даты его подписания обеими Сторонами"
    )
    valid_until = (
        f"до {contract.valid_until.strftime('%d.%m.%Y')}"
        if contract.valid_until
        else "до полного исполнения Сторонами своих обязательств"
    )
    return render_document_body(
        body_html if body_html else template.body_html,
        blocks=contract_block_values(contract, items, totals, ccy, seller=seller, seller_profile=seller_profile),
        scalars={
            "doc.number": contract.number,
            "doc.date": contract.created_at.strftime("%d.%m.%Y") if contract.created_at else "",
            "doc.total": money(contract.total_amount, ccy),
            "doc.currency": ccy,
            "doc.vat_rate": f"{int(round(float(vat_rate)))}" if vat_rate is not None else "",
            "doc.delivery_terms": _contract_delivery_terms(quote),
            "doc.valid_from": valid_from,
            "doc.valid_until": valid_until,
        },
    )


def receipt_block_values(payment, totals, ccy: str, *, seller=None, seller_profile=None) -> dict:
    """HTML блоков квитанции об оплате (D2a): ссылки, итоги, подписи."""
    return {
        "doc.refs": mark_safe(render_to_string("crm/blocks/_payment_refs.html", {"invoice": payment.invoice})),
        "doc.totals": mark_safe(render_to_string("crm/blocks/_totals.html", {"totals": totals})),
        "doc.signatures": mark_safe(
            render_to_string("crm/blocks/_signatures_invoice.html", {"seller_profile": seller_profile})
        ),
    }


def render_receipt_body(payment, totals, ccy: str, template, *, seller=None, seller_profile=None) -> str:
    """Тело квитанции по шаблону компании либо по платформенному образцу."""
    from crm.templatetags.document_format import money, money_words

    invoice = payment.invoice
    return render_document_body(
        template.body_html,
        blocks=receipt_block_values(payment, totals, ccy, seller=seller, seller_profile=seller_profile),
        scalars={
            "doc.number": payment.receipt_number,
            "doc.date": payment.paid_at.strftime("%d.%m.%Y") if payment.paid_at else "",
            "doc.total": money(payment.amount, ccy),
            "doc.total_words": money_words(payment.amount, ccy),
            "doc.currency": ccy,
            "doc.payment_method": payment.get_method_display(),
            "doc.invoice_paid": money(invoice.amount_paid, ccy),
            "doc.invoice_balance": money(invoice.balance_due, ccy),
        },
    )


def delivery_note_block_values(fulfillment, items, ccy: str, *, seller=None, seller_profile=None) -> dict:
    """HTML блоков накладной (D2b): ссылки, состав отправления, подписи двух рук."""
    deal = fulfillment.deal
    return {
        "doc.refs": mark_safe(render_to_string("crm/blocks/_delivery_refs.html", {"fulfillment": fulfillment})),
        "doc.items_table": mark_safe(render_to_string("crm/blocks/_delivery_items.html", {"items": items, "ccy": ccy})),
        "doc.signatures": mark_safe(
            render_to_string(
                "crm/blocks/_signatures_delivery.html",
                {
                    "seller": seller,
                    "seller_profile": seller_profile,
                    "company": deal.company,
                    "contact": getattr(deal, "contact", None),
                },
            )
        ),
    }


def render_delivery_note_body(fulfillment, items, ccy: str, template, *, seller=None, seller_profile=None) -> str:
    """Тело накладной по шаблону компании либо по платформенному образцу."""
    carrier_phrase = f" ({fulfillment.carrier})" if fulfillment.carrier else ""
    return render_document_body(
        template.body_html,
        blocks=delivery_note_block_values(fulfillment, items, ccy, seller=seller, seller_profile=seller_profile),
        scalars={
            "doc.number": delivery_note_number(fulfillment),
            "doc.date": fulfillment.shipped_at.strftime("%d.%m.%Y") if fulfillment.shipped_at else "",
            "doc.carrier_phrase": carrier_phrase,
            "doc.tracking": fulfillment.tracking_number or "",
        },
    )


def document_recipient_language(deal) -> str:
    """Язык, на котором получатель ЖДЁТ закрывающий документ (M1).

    Канон Odoo (`partner.lang`) и Stripe (`preferred_locales`): счёт и акт выставляет
    продавец, а читает их покупатель — язык того, кто нажал кнопку, к делу не относится.

    Берём язык активных членов компании-покупателя: если команда единодушна, документ
    печатается на нём; при расхождении (в компании и русско-, и англоязычные сотрудники)
    остаёмся на языке платформы, потому что документ ОДИН на всю сторону, а не на человека.
    Соло-сделка без компании-покупателя языка не сообщает — тоже язык платформы.
    """
    from django.conf import settings

    from core.i18n import resolve_user_language

    default = settings.LANGUAGE_CODE
    if deal is None or not getattr(deal, "company_id", None):
        return default
    from accounts.models import CustomUser

    users = CustomUser.objects.filter(memberships__company_id=deal.company_id, memberships__is_active=True)
    languages = {resolve_user_language(user) for user in users}
    if len(languages) == 1:
        return languages.pop()
    return default
