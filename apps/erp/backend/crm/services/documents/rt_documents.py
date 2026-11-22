"""Документы ERP на общем генераторе rt_docs (план 2026-11-12 п. 2.6; ADR-0020; `docs/architecture/rt-docs.md` §7).

Один генератор для писем EDS и документов ERP: бланк — те же реквизиты «Компании и бланка», что уходят в EDS событием,
коммерческий макет (`Layout.COMMERCIAL`: шапка с номером и датой, подвал на каждой странице), таблица позиций, итоги с НДС
и прописью, платёжные реквизиты — блоками `rt_docs.commercial`. Проект (SIGN-1) — знаком «ПРОЕКТ» самого генератора.

Какие виды уже идут здесь, задаёт `settings.RT_DOCS_DOCUMENTS` (по умолчанию — счёт): переключение по видам и откат одной
переменной окружения, пока виды переносятся по одному. Рендер — только в воркере Celery (B-094): жёсткий тайм-аут rt_docs
работает в главном потоке процесса задачи.
"""

from __future__ import annotations

import base64
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.utils.translation import gettext as _


def enabled(kind: str) -> bool:
    """Вид документа рендерится rt_docs (иначе — прежний шаблон Django)."""
    return kind in set(getattr(settings, "RT_DOCS_DOCUMENTS", ()))


def _lines(text: str | None) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def grid_enabled() -> bool:
    """Сетка документа (стандарт документов §4, план ДОК-4). Откат без выпуска кода — `RT_DOCS_GRID=0`."""
    return bool(getattr(settings, "RT_DOCS_GRID", True))


def _seller_name(seller, profile) -> str:
    return (getattr(profile, "legal_name", "") or getattr(seller, "name", "") or "").strip() or "—"


def _default_bank(seller):
    accounts = getattr(seller, "bank_accounts", None)
    if accounts is None:
        return None
    active = (
        accounts.filter(is_active=True)
        .select_related("currency", "bank_country")
        .order_by("-is_default", "order", "id")
    )
    return active.filter(currency__code="UZS").first() or active.first()


def _site(value: str) -> str:
    return re.sub(r"^https?://", "", (value or "").strip()).rstrip("/")


def footer_columns(seller, profile) -> tuple:
    """Подвал сетки из настроек компании (стандарт §4): компания и адрес; руководство и регистрация; контакты; банк;
    налоговые номера. Пустая колонка не печатается."""
    from rt_docs import FooterColumn

    name = _seller_name(seller, profile)
    columns = [
        FooterColumn(
            title=name,
            lines=tuple(_lines(getattr(profile, "legal_address", "") or getattr(seller, "legal_address", ""))[:3]),
        )
    ]
    management = []
    signer = (getattr(profile, "signatory_name", "") or "").strip()
    if signer:
        position = (getattr(profile, "signatory_position", "") or "").strip() or _("Директор")
        management.append(f"{position}: {signer}")
    registration = (getattr(seller, "registration_number", "") or "").strip()
    if registration:
        management.append(f"{_('Рег. №')} {registration}")
    if management:
        columns.append(FooterColumn(title=_("Руководство"), lines=tuple(management)))
    contacts = [
        f"{_('Тел.:')} {seller.phone}" if getattr(seller, "phone", "") else "",
        getattr(seller, "email", "") or "",
        _site(getattr(seller, "website", "")),
    ]
    if any(contacts):
        columns.append(FooterColumn(lines=tuple(line for line in contacts if line)))
    bank = _default_bank(seller)
    if bank is not None:
        from parties.banking import UZ, grouped, uses_iban

        country = getattr(bank.bank_country, "code", "") or UZ
        if country == UZ:
            bank_lines = [f"{_('МФО')} {bank.mfo}" if bank.mfo else "", f"{_('р/с')} {grouped(bank.account)}"]
        else:
            number = "IBAN" if uses_iban(country) else _("Счёт")
            bank_lines = [f"{number} {grouped(bank.account)}", f"SWIFT {bank.swift}" if bank.swift else ""]
        columns.append(FooterColumn(title=bank.bank_name or None, lines=tuple(line for line in bank_lines if line)))
    inn = (getattr(profile, "inn", "") or getattr(seller, "inn", "") or "").strip()
    if inn:
        columns.append(FooterColumn(lines=(f"{_('ИНН')} {inn}",)))
    return tuple(columns[:5])


def return_address(seller, profile) -> str:
    """Строка обратного адреса над окном конверта: название и первая строка адреса."""
    address = _lines(getattr(profile, "legal_address", "") or getattr(seller, "legal_address", ""))
    return " · ".join([_seller_name(seller, profile), *address[:2]])


def letterhead_of(seller, profile):
    """Бланк продавца для rt_docs: название, адрес, ИНН и банк строками, подвал, логотип и цвет профиля."""
    from rt_docs import Letterhead, Logo

    from accounts.services.letterhead_event import _logo

    name = (getattr(profile, "legal_name", "") or getattr(seller, "name", "") or "").strip()
    requisites = _lines(getattr(profile, "legal_address", "") or getattr(seller, "legal_address", ""))
    inn = (getattr(profile, "inn", "") or getattr(seller, "inn", "") or "").strip()
    if inn:
        requisites.append(f"{_('ИНН')} {inn}")
    requisites += _bank_lines(seller, profile)
    logo = None
    if profile is not None:
        payload, _omitted = _logo(profile)
        if payload:
            logo = Logo(base64.b64decode(payload["data_base64"]), payload["content_type"])
    accent = (getattr(profile, "accent_color", "") or "").strip()
    return Letterhead(
        company_name=name or "—",
        requisites=tuple(requisites),
        footer=tuple(_lines(getattr(profile, "footer_text", ""))),
        logo=logo,
        **({"accent": accent} if len(accent) == 7 and accent.startswith("#") else {}),
        footer_columns=footer_columns(seller, profile) if grid_enabled() and seller is not None else (),
        return_address=return_address(seller, profile) if grid_enabled() and seller is not None else None,
    )


def _bank_lines(seller, profile, currency: str | None = None, *, english: bool = False) -> list[str]:
    """Реквизиты основного счёта валюты документа (без него — в сумах), строками «подпись: значение» (ADR-0029 п. 5).

    Текст реквизитов из карточки компании и профиля документов не печатается: счета — один источник (ADR-0028 п. 3).
    """
    from parties.banking import print_rows
    from parties.models import Company

    from accounts.services.bank_accounts import default_account

    account = default_account(seller, currency) if isinstance(seller, Company) else None
    if account is None:
        return []
    rows = print_rows(account, english=english, with_party=False)
    return [f"{label}: {value}" if english else f"{_(label)}: {value}" for label, value in rows]


def _recipient_of(seller, currency: str, fallback: str) -> str:
    """Получатель платежа — владелец основного счёта валюты (латиницей для счёта за рубежом), иначе название продавца."""
    from parties.banking import UZ
    from parties.models import Company

    from accounts.services.bank_accounts import default_account

    account = default_account(seller, currency) if isinstance(seller, Company) else None
    if account is None:
        return fallback
    foreign = (getattr(account.bank_country, "code", "") or UZ) != UZ
    return (account.holder_name_latin if foreign else "") or account.holder_name or fallback


def _text(value: str, *, bold: bool = False) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if bold:
        node["marks"] = [{"type": "bold"}]
    return node


def _para(*parts: Any) -> dict[str, Any]:
    nodes = [_text(p) if isinstance(p, str) else p for p in parts if p not in ("", None)]
    # Пустой текстовый узел контракт тела не допускает (подписант не указан и т. п.).
    content = [n for n in nodes if n.get("type") != "text" or n.get("text")]
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def _party(title: str, name: str, lines: list[str]) -> list[dict[str, Any]]:
    return [_para(_text(title, bold=True)), _para(_text(name or "—", bold=True)), *[_para(line) for line in lines]]


def _parties(seller, profile, buyer, buyer_title: str | None = None) -> dict[str, Any]:
    """Две колонки без линий: «Поставщик» и «Плательщик» (у акта — «Покупатель») — как в прежних счёте и акте."""
    seller_name = (getattr(profile, "legal_name", "") or getattr(seller, "name", "") or "").strip()
    seller_inn = (getattr(profile, "inn", "") or getattr(seller, "inn", "") or "").strip()
    seller_lines = ([f"{_('ИНН:')} {seller_inn}"] if seller_inn else []) + _lines(
        getattr(profile, "legal_address", "") or getattr(seller, "legal_address", "")
    )
    buyer_lines: list[str] = []
    if getattr(buyer, "inn", ""):
        buyer_lines.append(f"{_('ИНН:')} {buyer.inn}")
    elif getattr(buyer, "registration_number", ""):
        country = getattr(getattr(buyer, "country", None), "name", "")
        buyer_lines.append(f"{_('Рег. номер:')} {buyer.registration_number}" + (f" ({country})" if country else ""))
    buyer_lines += _lines(getattr(buyer, "legal_address", ""))
    return {
        "type": "table",
        "attrs": {"columnWidths": [50, 50], "variant": "plain"},
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableCell", "content": _party(_("Поставщик"), seller_name, seller_lines)},
                    {
                        "type": "tableCell",
                        "content": _party(buyer_title or _("Плательщик"), getattr(buyer, "name", ""), buyer_lines),
                    },
                ],
            }
        ],
    }


def window_of(company, contact=None) -> tuple[tuple[str, ...], int | None]:
    """Адресат в окне конверта (стандарт §4 зона 4): организация полужирным, адрес, ИНН; без компании — контакт."""
    if company is not None:
        lines = [company.name or "—", *_lines(getattr(company, "legal_address", ""))[:2]]
        if getattr(company, "inn", ""):
            lines.append(f"{_('ИНН')} {company.inn}")
        return tuple(lines), 0
    if contact is not None:
        lines = [getattr(contact, "position", "") or "", contact.name or "—"]
        lines = [line for line in lines if line]
        return tuple(lines), len(lines) - 1
    return (), None


def contact_rows(company, contact=None) -> tuple:
    """«Контактное лицо» и «Почта» под адресатом."""
    from parties.models import Company
    from parties.people import contact_name
    from rt_docs import InfoRow

    if isinstance(company, Company):
        person = contact_name(company).strip()
    else:  # образец предпросмотра
        person = (getattr(company, "contact_person", "") or "").strip() if company is not None else ""
    email = ""
    if contact is not None:
        person = person or (getattr(contact, "name", "") or "").strip()
        email = (getattr(contact, "email", "") or "").strip()
    rows = []
    if person:
        rows.append(InfoRow(_("Контактное лицо"), person))
    if email:
        rows.append(InfoRow(_("Почта"), email))
    return tuple(rows)


def _article_of(item) -> str:
    """Наш артикул строки: карточка каталога (ADR-0027) — её артикул."""
    product = getattr(getattr(item, "source_quote_item", None), "product", None) or getattr(item, "product", None)
    return (getattr(product, "sku", "") or "").strip()


def _unit_of(item) -> str:
    return (getattr(getattr(item, "source_quote_item", None), "unit", "") or getattr(item, "unit", "") or "").strip()


def _local_date(value):
    """Дата документа по часовому поясу компании (Ташкент), а не UTC: счёт от 15.11 не печатается «от 14.11»."""
    from datetime import datetime

    from django.utils import timezone

    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def _date_text(value) -> str:
    day = _local_date(value)
    return day.strftime("%d.%m.%Y") if day else ""


def _item_lines(items) -> list:
    """Позиции счёта (и акта, который его зеркалит) — строками таблицы: цена и сумма без НДС."""
    from rt_docs.commercial import Line

    return [
        Line(
            name=it.description,
            quantity=Decimal(it.quantity),
            price=Decimal(it.unit_price_excl_vat),
            amount=Decimal(it.line_total_excl_vat),
        )
        for it in items
    ]


def _sums(totals: dict[str, Any]):
    """Итоги `document_totals` → `rt_docs.commercial.Totals`."""
    from rt_docs.commercial import Totals

    return Totals(
        subtotal=Decimal(totals["subtotal"] or 0),
        vat_amount=Decimal(totals["vat_amount"] or 0),
        total=Decimal(totals["total"] or 0),
        vat_rate=Decimal(totals["vat_rate"]) if totals.get("vat_rate") else None,
        paid=Decimal(totals["amount_paid"]) if totals.get("amount_paid") else None,
        balance=Decimal(totals["balance_due"]) if totals.get("balance_due") is not None else None,
    )


_PLACE_DATE_RE = re.compile(r"<p>([^<]*\S)\s*<span>([^<]+)</span></p>")


def _template_body(body_html: str, *, scalars: dict[str, Any], blocks: dict[str, Any], lang: str) -> dict[str, Any]:
    """Шаблон ERP (санитизированный `body_html`) → тело rt_docs: скаляры — текстом (экранированы), `{{doc.*}}` блоков —
    узлами-блоками `html_to_body`, данные которых передаются в рендер. Неизвестный код остаётся текстом, как и раньше.
    """
    from django.utils.html import escape
    from rt_docs import html_to_body, load_catalog

    from crm.services.document_placeholders import PLACEHOLDER_RE

    # «г. Ташкент<span>дата</span>»: прежняя вёрстка разносила место и дату по краям строки, в теле rt_docs такого
    # выравнивания нет — печатаем через запятую, а не слитно.
    body_html = _PLACE_DATE_RE.sub(r"<p>\1, \2</p>", body_html or "")

    def sub(match) -> str:
        code = match.group(1).strip()
        if code in blocks:
            return "{{" + code + "}}"
        if code in scalars:
            return escape("" if scalars[code] is None else str(scalars[code]))
        return match.group(0)

    return html_to_body(PLACEHOLDER_RE.sub(sub, body_html or ""), lang=lang, catalog=load_catalog()).body


def invoice_pdf(invoice, items, totals: dict[str, Any], brand: dict[str, Any], *, draft: bool, body_html: str) -> bytes:
    """Счёт на rt_docs: рамка прежнего счёта (оплата до, договор, «Поставщик» и «Плательщик») и тело по шаблону
    компании, замороженной редакции или образцу платформы; блоки — позиции, итоги с НДС и прописью, платёжные
    реквизиты с назначением, примечание, подписи руководителя и главного бухгалтера."""
    from rt_docs import DocumentMeta, Layout, Money, format_money
    from rt_docs.commercial import items_table, payment_requisites, totals_block
    from rt_docs.pdf import render_pdf

    from crm.services.document_blocks import _draft_scalars, format_document_date

    lang = "ru"
    seller, profile = brand.get("seller"), brand.get("seller_profile")
    ccy = totals.get("ccy") or "UZS"
    issued = invoice.issued_at or invoice.created_at
    lines = _item_lines(items)
    sums = _sums(totals)
    if draft:
        purpose = _("Оплата по счёту")
    else:
        purpose = _("Оплата по счёту № %(number)s от %(doc_date)s") % {
            "number": invoice.number,
            "doc_date": _date_text(issued),
        }
    if invoice.contract_id:
        purpose += _(", договор № %(contract_number)s") % {"contract_number": invoice.contract.number}
    purpose += _(", в т.ч. НДС %(vat_amount)s.") % {
        "vat_amount": format_money(Money(Decimal(invoice.vat_amount or 0), ccy), lang)
    }
    recipient = (getattr(profile, "legal_name", "") or getattr(seller, "name", "") or "—").strip()
    inn = (getattr(profile, "inn", "") or getattr(seller, "inn", "") or "").strip()
    signer = (getattr(profile, "signatory_name", "") or "").strip()
    grid = grid_enabled()
    if grid:
        from rt_docs.commercial import grid_totals_block, stacked_items_table

        lines = [
            replace(line, article=_article_of(item), unit=_unit_of(item))
            for line, item in zip(lines, items, strict=True)
        ]
    blocks: dict[str, Any] = {
        "doc.items_table": (
            stacked_items_table(lines, ccy, lang) if grid else items_table(lines, ccy, lang, with_unit=False)
        ),
        "doc.totals": (grid_totals_block(sums, ccy, lang) if grid else totals_block(sums, ccy, lang)),
        "doc.payment_requisites": payment_requisites(
            lang,
            recipient=_recipient_of(seller, ccy, recipient),
            inn=inn,
            bank_lines=_bank_lines(seller, profile, ccy, english=lang == "en"),
            purpose=purpose,
        ),
        "doc.notes": (
            [_para(_text(_("Примечание:"), bold=True)), *[_para(line) for line in _lines(invoice.notes)]]
            if (invoice.notes or "").strip()
            else [_para()]
        ),
        "doc.signatures": [
            {
                "type": "signature",
                "attrs": {
                    "parties": [
                        {"role": _("Руководитель:"), **({"name": signer} if signer else {})},
                        {"role": _("Главный бухгалтер:")},
                    ],
                    "stamp": True,
                },
            }
        ],
    }
    scalars = _draft_scalars(
        {
            "doc.number": invoice.number,
            "doc.date": format_document_date(issued),
            "doc.total": format_money(Money(Decimal(invoice.total_incl_vat or 0), ccy), lang),
            "doc.currency": ccy,
        },
        draft,
    )
    body = _template_body(body_html, scalars=scalars, blocks=blocks, lang=lang)
    refs: list[str] = []
    if invoice.due_date:
        refs.append(_("оплата до %(due)s") % {"due": _date_text(invoice.due_date)})
    if invoice.contract_id:
        refs.append(_("по договору № %(contract_number)s") % {"contract_number": invoice.contract.number})
    if grid:
        meta = _invoice_grid_meta(invoice, issued, draft=draft)
    else:
        head = ([_para("; ".join(refs))] if refs else []) + [_parties(seller, profile, invoice.deal.company)]
        body["doc"]["content"] = head + body["doc"]["content"]
        meta = DocumentMeta(title=_("Счёт на оплату"), number=invoice.number, date=_local_date(issued))
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=meta,
        blocks=blocks,
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf


def _invoice_grid_meta(invoice, issued, *, draft: bool = False):
    """Счёт в сетке: инфоблок (номер, дата, оплатить до, договор, проект), плательщик в окне конверта."""
    from rt_docs import DocumentMeta, InfoRow

    deal = invoice.deal
    info = [
        InfoRow(_("Счёт №"), invoice.number or "—", code=True, role="number"),
        InfoRow(_("Дата"), _date_text(issued), role="date"),
    ]
    if invoice.due_date:
        info.append(InfoRow(_("Оплатить до"), _date_text(invoice.due_date)))
    if invoice.contract_id:
        info.append(InfoRow(_("Договор"), f"№ {invoice.contract.number}" + _dated(invoice.contract.created_at)))
    if getattr(deal, "number", ""):
        info.append(InfoRow(_("Проект"), deal.number, code=True))
    addressee, strong = window_of(deal.company, getattr(deal, "contact", None))
    return DocumentMeta(
        title=_("Счёт № %(number)s") % {"number": _("без номера") if draft else (invoice.number or "—")},
        kind_label=_("Счёт на оплату"),
        number=invoice.number,
        date=_local_date(issued),
        addressee=addressee,
        addressee_strong=strong,
        info=tuple(info),
    )


#: Линия подписи в колонке сторон акта (контракт тела не знает «линии» вне узла `signature`).
_SIGN_LINE = "_" * 32


def _moment(value) -> str:
    from django.utils import timezone

    return timezone.localtime(value).strftime("%d.%m.%Y %H:%M") if value else ""


def _dated(value) -> str:
    return " " + _("от %(issued)s") % {"issued": _date_text(value)} if value else ""


def _act_refs(act, invoice) -> list[dict[str, Any]]:
    """Блок `{{doc.refs}}`: сделка, договор и счёт — как в прежнем акте."""
    parts = [f"{_('Сделка:')} #{act.deal_id}"]
    if act.contract_id:
        parts.append(f"{_('Договор:')} {act.contract.number}" + _dated(act.contract.created_at))
    if invoice is not None:
        parts.append(f"{_('Счёт:')} {invoice.number}" + _dated(invoice.issued_at))
    return [_para(" · ".join(parts))]


def _act_signatures(act, seller, profile) -> list[dict[str, Any]]:
    """Подписи акта двумя колонками: ПЭП-штамп исполнителя (подписант, должность, основание, код проверки) и подпись
    заказчика — как в прежнем блоке; QR проверки печатает сам rt_docs по коду в `DocumentMeta`."""
    seller_cell = [
        _para(_text(_("От Поставщика:"), bold=True)),
        _para((getattr(profile, "legal_name", "") or getattr(seller, "name", "") or "—").strip()),
        _para(_SIGN_LINE),
    ]
    if act.verification_code:
        position = act.signatory_position + (f" · {act.signatory_basis_text}" if act.signatory_basis_text else "")
        seller_cell += [
            _para(_text(act.signatory_name, bold=True)),
            _para(f"{_('Официальная подпись')} · {_moment(act.issuer_signed_at)}"),
            *([_para(position)] if position.strip() else []),
            _para(f"{_('Код проверки:')} ", _text(act.verification_code, bold=True)),
        ]
    elif act.issuer_signer_id:
        seller_cell += [
            _para(f"{_('Простая электронная подпись')} · {_moment(act.issuer_signed_at)}"),
            _para(f"{_('Идентификация:')} {act.issuer_signer.email}"),
        ]
    elif (getattr(profile, "signatory_name", "") or "").strip():
        position = (getattr(profile, "signatory_position", "") or "").strip() or _("Подписант")
        seller_cell.append(_para(f"{position}: {profile.signatory_name}"))
    else:
        seller_cell.append(_para(_("Подпись / дата")))
    seller_cell.append(_para(_("М.П.")))

    company, contact = act.deal.company, getattr(act.deal, "contact", None)
    buyer = company.name if company else (getattr(contact, "name", "") or "—")
    buyer_cell = [_para(_text(_("От Покупателя:"), bold=True)), _para(buyer), _para(_SIGN_LINE)]
    if act.acceptor_signer_id:
        buyer_cell += [
            _para(f"{_('Простая электронная подпись')} · {_moment(act.acceptor_signed_at)}"),
            _para(f"{_('Идентификация:')} {act.acceptor_signer.email}"),
        ]
    else:
        buyer_cell.append(_para(_("Подпись / дата")))
    buyer_cell.append(_para(_("М.П.")))
    return [
        {
            "type": "table",
            "attrs": {"columnWidths": [50, 50], "variant": "plain"},
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableCell", "content": seller_cell},
                        {"type": "tableCell", "content": buyer_cell},
                    ],
                }
            ],
        }
    ]


def act_pdf(act, totals: dict[str, Any], brand: dict[str, Any], *, draft: bool, body_html: str) -> bytes:
    """Акт на rt_docs: тело по шаблону компании, замороженной редакции или образцу платформы; блоки — ссылки на
    сделку, договор и счёт, позиции счёта (акт его зеркалит), итоги с НДС и прописью, оговорка о приёмке, подписи
    сторон. Подписанный акт печатает код и QR проверки (ADR-0024 п. 5), проект — знак «ПРОЕКТ»."""
    from django.conf import settings as django_settings
    from rt_docs import DocumentMeta, Layout, Money, format_money
    from rt_docs.commercial import items_table, totals_block
    from rt_docs.pdf import render_pdf

    from crm.document_wording import resolve_wording_selected
    from crm.services.document_blocks import _draft_scalars

    lang = "ru"
    seller, profile = brand.get("seller"), brand.get("seller_profile")
    ccy = totals.get("ccy") or "UZS"
    invoice = act.invoice
    closing = resolve_wording_selected(getattr(act, "wording_selections", None), profile, "act_closing_text")
    grid = grid_enabled()
    act_items = list(invoice.items.select_related("source_quote_item__product")) if invoice is not None else []
    if grid:
        from rt_docs.commercial import grid_totals_block, stacked_items_table

        act_lines = [
            replace(line, article=_article_of(item), unit=_unit_of(item))
            for line, item in zip(_item_lines(act_items), act_items, strict=True)
        ]
        items_block = stacked_items_table(act_lines, ccy, lang)
        totals_nodes = grid_totals_block(_sums(totals), ccy, lang, total_label=_("Всего"))
    else:
        items_block = items_table(_item_lines(act_items), ccy, lang, with_unit=False)
        totals_nodes = totals_block(_sums(totals), ccy, lang)
    blocks: dict[str, Any] = {
        # В сетке сделка, договор и счёт — в инфоблоке: строка ссылок не печатается.
        "doc.refs": [_para()] if grid else _act_refs(act, invoice),
        "doc.items_table": items_block,
        "doc.totals": totals_nodes,
        "doc.act_closing": [_para(line) for line in _lines(closing)] or [_para()],
        "doc.signatures": _act_signatures(act, seller, profile),
    }
    scalars = _draft_scalars(
        {
            "doc.number": act.number,
            "doc.date": _date_text(act.issued_at),
            "doc.total": format_money(Money(Decimal(act.total_amount or 0), ccy), lang),
        },
        draft,
    )
    body = _template_body(body_html, scalars=scalars, blocks=blocks, lang=lang)
    company, contact = act.deal.company, getattr(act.deal, "contact", None)
    code = "" if draft else (act.verification_code or "")
    cabinet = (getattr(django_settings, "CABINET_URL", "") or "").rstrip("/")
    verification = {
        "verification_code": code or None,
        "verification_url": f"{cabinet}/v/{code}" if code and cabinet else None,
    }
    if grid:
        meta = _act_grid_meta(act, invoice, draft=draft, **verification)
    else:
        body["doc"]["content"] = [_parties(seller, profile, company or contact, _("Покупатель"))] + body["doc"][
            "content"
        ]
        meta = DocumentMeta(
            title=_("Акт приёма-передачи"),
            number=act.number,
            date=_local_date(act.issued_at or act.created_at),
            **verification,
        )
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=meta,
        blocks=blocks,
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf


def _act_grid_meta(act, invoice, *, draft: bool, verification_code, verification_url):
    """Акт в сетке: инфоблок (номер, дата, договор, счёт, проект), покупатель в окне конверта."""
    from rt_docs import DocumentMeta, InfoRow

    deal = act.deal
    issued = act.issued_at or act.created_at
    info = [
        InfoRow(_("Акт №"), act.number or "—", code=True, role="number"),
        InfoRow(_("Дата"), _date_text(issued), role="date"),
    ]
    if act.contract_id:
        info.append(InfoRow(_("Договор"), f"№ {act.contract.number}" + _dated(act.contract.created_at)))
    if invoice is not None:
        info.append(InfoRow(_("Счёт"), invoice.number or "—", code=True))
    if getattr(deal, "number", ""):
        info.append(InfoRow(_("Проект"), deal.number, code=True))
    addressee, strong = window_of(deal.company, getattr(deal, "contact", None))
    return DocumentMeta(
        title=_("Акт № %(number)s") % {"number": _("без номера") if draft else (act.number or "—")},
        kind_label=_("Акт приёма-передачи"),
        number=act.number,
        date=_local_date(issued),
        addressee=addressee,
        addressee_strong=strong,
        info=tuple(info),
        verification_code=verification_code,
        verification_url=verification_url,
    )


def _two_columns(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "attrs": {"columnWidths": [50, 50], "variant": "plain"},
        "content": [
            {
                "type": "tableRow",
                "content": [{"type": "tableCell", "content": left}, {"type": "tableCell", "content": right}],
            }
        ],
    }


def _requisites(title: str, name: str, org, profile=None) -> list[dict[str, Any]]:
    """Полные реквизиты стороны договора: ИНН (или рег. номер), адрес, банк, телефон — как в прежнем блоке."""
    lines: list[str] = []
    inn = (getattr(profile, "inn", "") or getattr(org, "inn", "") or "").strip()
    if inn:
        lines.append(f"{_('ИНН:')} {inn}")
    elif getattr(org, "registration_number", ""):
        country = getattr(getattr(org, "country", None), "name", "")
        lines.append(f"{_('Рег. номер:')} {org.registration_number}" + (f" ({country})" if country else ""))
    address = (getattr(profile, "legal_address", "") or getattr(org, "legal_address", "") or "").strip()
    if address:
        lines.append(f"{_('Адрес:')} {address}")
    lines += _bank_lines(org, profile)
    if getattr(org, "phone", ""):
        lines.append(f"{_('Тел.:')} {org.phone}")
    signer = (getattr(profile, "signatory_name", "") or "").strip()
    if signer:
        position = (getattr(profile, "signatory_position", "") or "").strip() or _("Подписант")
        lines.append(f"{position}: {signer}")
    return [_para(_text(title, bold=True)), _para(_text(name or "—", bold=True)), *[_para(line) for line in lines]]


def _pep(signer, signed_at) -> list[dict[str, Any]]:
    who = signer.get_full_name() or signer.email
    return [
        _para(who),
        _para(f"{_('Простая электронная подпись')} · {_moment(signed_at)}"),
        _para(f"{_('Идентификация:')} {signer.email}"),
    ]


def _contract_tail(contract, seller, profile, article_no: str) -> list[dict[str, Any]]:
    """Блок `{{doc.requisites_and_signatures}}`: статья «Реквизиты и подписи Сторон», реквизиты обеих сторон, подписи
    (официальная — с кодом проверки, ПЭП — с идентификацией) и оговорка о ПЭП."""
    company = contract.deal.company
    seller_name = (getattr(profile, "legal_name", "") or getattr(seller, "name", "") or _("Поставщик")).strip()
    seller_sign = [_para(_text(_("От Поставщика:"), bold=True)), _para(_SIGN_LINE)]
    if contract.verification_code:
        position = contract.signatory_position + (
            f" · {contract.signatory_basis_text}" if contract.signatory_basis_text else ""
        )
        seller_sign += [
            _para(_text(contract.signatory_name, bold=True)),
            _para(f"{_('Официальная подпись')} · {_moment(contract.signed_at)}"),
            *([_para(position)] if position.strip() else []),
            _para(f"{_('Код проверки:')} ", _text(contract.verification_code, bold=True)),
        ]
    elif contract.manager_signer_id:
        seller_sign += _pep(contract.manager_signer, contract.manager_signed_at)
    else:
        seller_sign.append(_para(_("Подпись / дата")))
    seller_sign.append(_para(_("М.П.")))
    buyer_sign = [_para(_text(_("От Покупателя:"), bold=True)), _para(_SIGN_LINE)]
    if contract.client_signer_id:
        buyer_sign += _pep(contract.client_signer, contract.client_signed_at)
    else:
        buyer_sign.append(_para(_("Подпись / дата")))
    buyer_sign.append(_para(_("М.П.")))
    nodes = [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [_text(_("%(no)s. Реквизиты и подписи Сторон") % {"no": article_no})],
        },
        _two_columns(
            _requisites(_("Поставщик"), seller_name, seller, profile),
            _requisites(_("Покупатель"), getattr(company, "name", "") or _("Покупатель"), company),
        ),
        _two_columns(seller_sign, buyer_sign),
    ]
    if contract.manager_signer_id or contract.client_signer_id:
        nodes.append(
            _para(
                _(
                    "Документ подписан простой электронной подписью (ПЭП) в соответствии с соглашением сторон об "
                    "электронном документообороте. Подписант идентифицирован по учётной записи платформы; дата и "
                    "время подписания зафиксированы системой."
                )
            )
        )
    return nodes


def contract_pdf(
    contract, items, totals: dict[str, Any], brand: dict[str, Any], *, draft: bool, body_html: str
) -> bytes:
    """Договор поставки на rt_docs: стороны в шапке, статьи по шаблону компании, замороженной редакции или образцу;
    блоки — спецификация (Приложение № 1), итоги, формулировки приёмки и ответственности, особые условия, примечание,
    реквизиты и подписи сторон. Подписанный — с кодом и QR проверки, проект — знаком «ПРОЕКТ»."""
    from django.conf import settings as django_settings
    from rt_docs import Layout, Money, format_money
    from rt_docs.commercial import Line, items_table, totals_block
    from rt_docs.pdf import render_pdf

    from crm.document_wording import resolve_wording_selected
    from crm.services.document_blocks import _contract_delivery_terms, _draft_scalars, format_document_date

    lang = "ru"
    seller, profile = brand.get("seller"), brand.get("seller_profile")
    ccy = totals.get("ccy") or "UZS"
    quote = contract.quote if contract.quote_id else None
    selections = getattr(contract, "wording_selections", None)

    def wording(field: str) -> list[dict[str, Any]]:
        return [_para(line) for line in _lines(resolve_wording_selected(selections, profile, field))] or [_para()]

    extra_terms = resolve_wording_selected(selections, profile, "contract_extra_terms_text").strip()
    lines = [
        Line(
            name=(it.product.name if it.product_id else it.imported_raw_name) or "—",
            quantity=Decimal(it.quantity),
            price=Decimal(it.final_price_excl_vat or 0),
            amount=Decimal(it.line_total or 0),
            unit=it.unit or "",
        )
        for it in items
    ]
    grid = grid_enabled()
    if grid:
        from rt_docs.commercial import grid_totals_block, stacked_items_table

        lines = [
            replace(line, article=(getattr(it.product, "sku", "") or "") if it.product_id else "")
            for line, it in zip(lines, items, strict=True)
        ]
        spec = stacked_items_table(lines, ccy, lang)
        totals_nodes = grid_totals_block(_sums(totals), ccy, lang, total_label=_("Всего"))
    else:
        spec = items_table(lines, ccy, lang, with_unit=True)
        totals_nodes = totals_block(_sums(totals), ccy, lang)
    blocks: dict[str, Any] = {
        "doc.spec_table": [_para(_text(_("Приложение № 1. Спецификация"), bold=True)), *spec],
        "doc.totals": totals_nodes,
        "doc.contract_acceptance": wording("contract_acceptance_text"),
        "doc.contract_liability": wording("contract_liability_text"),
        "doc.extra_terms_article": (
            [
                {"type": "heading", "attrs": {"level": 2}, "content": [_text(_("10. Особые условия"))]},
                *[_para(line) for line in _lines(extra_terms)],
            ]
            if extra_terms
            else [_para()]
        ),
        "doc.notes": (
            [
                _para(_text(_("Дополнительные условия:"), bold=True)),
                *[_para(line) for line in _lines(contract.notes)],
            ]
            if (contract.notes or "").strip()
            else [_para()]
        ),
        "doc.requisites_and_signatures": _contract_tail(contract, seller, profile, "11" if extra_terms else "10"),
    }
    vat_rate = getattr(quote, "vat_rate", None) if quote is not None else None
    scalars = _draft_scalars(
        {
            "doc.number": contract.number,
            "doc.date": format_document_date(contract.created_at),
            "doc.total": format_money(Money(Decimal(contract.total_amount or 0), ccy), lang),
            "doc.currency": ccy,
            "doc.vat_rate": f"{int(round(float(vat_rate)))}" if vat_rate is not None else "",
            "doc.delivery_terms": _contract_delivery_terms(quote),
            "doc.valid_from": (
                _("с %(day)s") % {"day": _date_text(contract.valid_from)}
                if contract.valid_from
                else _("с даты его подписания обеими Сторонами")
            ),
            "doc.valid_until": (
                _("до %(day)s") % {"day": _date_text(contract.valid_until)}
                if contract.valid_until
                else _("до полного исполнения Сторонами своих обязательств")
            ),
        },
        draft,
    )
    body = _template_body(body_html, scalars=scalars, blocks=blocks, lang=lang)
    body["doc"]["content"] = [_parties(seller, profile, contract.deal.company, _("Покупатель"))] + body["doc"][
        "content"
    ]
    code = "" if draft else (contract.verification_code or "")
    cabinet = (getattr(django_settings, "CABINET_URL", "") or "").rstrip("/")
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=_contract_meta(contract, quote, draft=draft, grid=grid, code=code, cabinet=cabinet),
        blocks=blocks,
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf


def _contract_meta(contract, quote, *, draft: bool, grid: bool, code: str, cabinet: str):
    """Договор: в сетке — вид и инфоблок (номер, дата, место, основание, проект) без окна конверта; стороны — в теле."""
    from rt_docs import DocumentMeta, InfoRow

    verification = {
        "verification_code": code or None,
        "verification_url": f"{cabinet}/v/{code}" if code and cabinet else None,
    }
    if not grid:
        return DocumentMeta(
            title=_("Договор поставки"), number=contract.number, date=_local_date(contract.created_at), **verification
        )
    info = [
        InfoRow(_("Договор №"), contract.number or "—", code=True, role="number"),
        InfoRow(_("Дата"), _date_text(contract.created_at), role="date"),
        InfoRow(_("Место"), _("г. Ташкент")),
    ]
    if quote is not None and quote.number:
        info.append(InfoRow(_("Основание"), _("КП № %(number)s") % {"number": quote.number}))
    if getattr(contract.deal, "number", ""):
        info.append(InfoRow(_("Проект"), contract.deal.number, code=True))
    return DocumentMeta(
        kind_label=_("Договор поставки"),
        number=contract.number,
        date=_local_date(contract.created_at),
        info=tuple(info),
        window=False,
        **verification,
    )


def _cell(
    content: list[dict[str, Any]] | str, *, header: bool = False, numeric: bool = False, colspan: int = 1, **attrs
) -> dict[str, Any]:
    paras = [_para(content)] if isinstance(content, str) else content
    node: dict[str, Any] = {"type": "tableHeader" if header else "tableCell", "content": paras or [_para()]}
    cell_attrs = {**({"numeric": True} if numeric else {}), **({"colspan": colspan} if colspan > 1 else {}), **attrs}
    if cell_attrs:
        node["attrs"] = cell_attrs
    return node


def _quote_lines_table(rows: list[dict[str, Any]], quote, *, lead: bool, numbered: bool) -> dict:
    """Таблица КП как прежде: разделы с подытогом и примечания во всю ширину, артикул и ГОСТ под названием, колонка
    «Срок / наличие» — только когда хоть у одной позиции свой срок; цены и суммы без НДС, расходы уже в цене строки."""
    from rt_docs import format_number

    def money(value) -> str:
        return format_number(Decimal(value or 0), "ru")

    def qty(item) -> str:
        from crm.templatetags.document_format import qty as qty_filter

        return qty_filter(item.get("quantity"), item.get("unit"))

    def lead_text(item) -> str:
        if item.get("lead_time_days"):
            return _("до %(days)s дн.") % {"days": item["lead_time_days"]}
        if quote.effective_delivery_lead_time_days:
            return _("до %(days)s дн.") % {"days": quote.effective_delivery_lead_time_days}
        return _("уточняется") if item.get("lead_pending") else _("В наличии")

    columns = [_("№"), _("Наименование"), _("Кол-во"), *([_("Срок / наличие")] if lead else [])]
    # Заголовки сумм — вправо, но с переносом (числовая ячейка не переносится и наползает на соседнюю).
    header = [_cell(title, header=True) for title in columns] + [
        _cell(_("Цена за ед. без НДС"), header=True, align="right"),
        _cell(_("Сумма без НДС"), header=True, align="right"),
    ]
    width = len(header)
    out = [{"type": "tableRow", "content": header}]
    for index, item in enumerate(rows, start=1):
        kind = item.get("display_type", "ITEM")
        if kind == "SECTION":
            out.append(
                {
                    "type": "tableRow",
                    "content": [
                        _cell([_para(_text(item.get("imported_raw_name") or "—", bold=True))], colspan=width - 1),
                        _cell([_para(_text(money(item.get("section_subtotal")), bold=True))], numeric=True),
                    ],
                }
            )
            continue
        if kind == "NOTE":
            note = (item.get("imported_raw_name") or "").strip()
            italic = {"type": "text", "text": note, "marks": [{"type": "italic"}]} if note else ""
            out.append({"type": "tableRow", "content": [_cell([_para(italic)], colspan=width)]})
            continue
        product = item.get("product")
        name = (getattr(product, "name", "") or item.get("imported_raw_name") or "—").strip() or "—"
        sub = " · ".join(
            part
            for part in (
                f"{_('Арт.:')} {item['mpn']}" if item.get("mpn") else "",
                item.get("gost_drawing") or "",
            )
            if part
        )
        cells = [
            _cell(str(item.get("line_no") if not numbered else index)),
            _cell([_para(_text(name, bold=True)), *([_para(sub)] if sub else [])]),
            _cell(qty(item), align="center"),
        ]
        if lead:
            cells.append(_cell(lead_text(item), align="center"))
        cells += [
            _cell(money(item.get("final_price_excl_vat")), numeric=True),
            _cell(money(item.get("line_total")), numeric=True),
        ]
        out.append({"type": "tableRow", "content": cells})
    widths = [5, 43, 10, 12, 15, 15] if lead else [5, 55, 10, 15, 15]
    return {"type": "table", "attrs": {"columnWidths": widths, "variant": "grid"}, "content": out}


def _note_para(*parts: Any) -> dict[str, Any]:
    node = _para(*parts)
    node["attrs"] = {"variant": "note"}
    return node


def _quote_grid_table(rows: list[dict[str, Any]], quote, *, lead: bool, numbered: bool) -> dict:
    """Таблица КП в сетке (стандарт §6 п. 2): позиция стопкой — наш артикул моно, название, ГОСТ и артикул
    изготовителя примечанием; цена с «/ 1 ед.»; разделы с подытогом и примечания во всю ширину, как прежде."""
    from rt_docs import format_number

    def money(value) -> str:
        amount = Decimal(value or 0)
        return format_number(amount, "ru", decimals=0 if amount == amount.to_integral_value() else 2)

    def qty(item) -> str:
        from crm.templatetags.document_format import qty as qty_filter

        return qty_filter(item.get("quantity"), item.get("unit"))

    def lead_text(item) -> str:
        if item.get("lead_time_days"):
            return _("%(days)s дн.") % {"days": item["lead_time_days"]}
        if quote.effective_delivery_lead_time_days:
            return _("%(days)s дн.") % {"days": quote.effective_delivery_lead_time_days}
        return _("уточняется") if item.get("lead_pending") else _("в наличии")

    header = [
        _cell(_("№"), header=True),
        _cell(_("Артикул · Позиция"), header=True),
        *([_cell(_("Срок"), header=True, numeric=True)] if lead else []),
        _cell(_("Кол-во"), header=True, numeric=True),
        _cell(_("Цена, сум"), header=True, numeric=True),
        _cell(_("Сумма, сум"), header=True, numeric=True),
    ]
    width = len(header)
    out = [{"type": "tableRow", "content": header}]
    for index, item in enumerate(rows, start=1):
        kind = item.get("display_type", "ITEM")
        if kind == "SECTION":
            out.append(
                {
                    "type": "tableRow",
                    "content": [
                        _cell([_para(_text(item.get("imported_raw_name") or "—", bold=True))], colspan=width - 1),
                        _cell([_para(_text(money(item.get("section_subtotal")), bold=True))], numeric=True),
                    ],
                }
            )
            continue
        if kind == "NOTE":
            note = (item.get("imported_raw_name") or "").strip()
            italic = {"type": "text", "text": note, "marks": [{"type": "italic"}]} if note else ""
            out.append({"type": "tableRow", "content": [_cell([_para(italic)], colspan=width)]})
            continue
        product = item.get("product")
        name = (getattr(product, "name", "") or item.get("imported_raw_name") or "—").strip() or "—"
        sku = (getattr(product, "sku", "") or "").strip()
        details = " · ".join(
            part
            for part in (
                item.get("gost_drawing") or "",
                f"{_('Арт. изготовителя')} {item['mpn']}" if item.get("mpn") else "",
            )
            if part
        )
        stack = [
            *([_note_para({"type": "text", "text": sku, "marks": [{"type": "code"}]})] if sku else []),
            _para(name),
            *([_note_para(details)] if details else []),
        ]
        unit = (item.get("unit") or "").strip()
        price = [_para(money(item.get("final_price_excl_vat")))] + ([_note_para(f"/ 1 {unit}")] if unit else [])
        cells = [
            _cell(str(item.get("line_no") if not numbered else index)),
            _cell(stack),
            *([_cell(lead_text(item), numeric=True)] if lead else []),
            _cell(qty(item), numeric=True),
            _cell(price, numeric=True),
            _cell(money(item.get("line_total")), numeric=True),
        ]
        out.append({"type": "tableRow", "content": cells})
    widths = [5, 43, 9, 12, 16, 15] if lead else [5, 50, 13, 16, 16]
    return {"type": "table", "attrs": {"columnWidths": widths, "variant": "grid"}, "content": out}


def _label_rows(rows: list[tuple[str, str]], widths: tuple[int, int] = (35, 65)) -> dict[str, Any]:
    return {
        "type": "table",
        "attrs": {"columnWidths": list(widths), "variant": "plain"},
        "content": [
            {"type": "tableRow", "content": [_cell([_para(_text(label, bold=True))]), _cell(value)]}
            for label, value in rows
            if value
        ],
    }


def quote_pdf(quote, *, items, optional_items, extras: dict[str, Any], brand: dict[str, Any], draft: bool) -> bytes:
    """КП на rt_docs — письмо-предложение, как прежде: адресат справа, сведения о КП и менеджере, сопроводительный
    текст, позиции (проекция для клиента: без себестоимости и наценки, расходы — в цене строки), итоги с НДС и
    прописью, опциональные позиции вне итога, условия поставки, штамп подписи. QR — проверка подписанного КП или
    онлайн-версия отправленного; проект — знаком «ПРОЕКТ» без номера."""
    from django.conf import settings as django_settings
    from rt_docs import DocumentMeta, Layout
    from rt_docs.commercial import totals_block
    from rt_docs.pdf import render_pdf

    from crm.services.documents import public_quote_url

    lang = "ru"
    seller, profile = brand.get("seller"), brand.get("seller_profile")
    totals = extras["totals"]
    ccy = totals.get("ccy") or "UZS"
    lead = bool(brand.get("show_lead_time", True)) and any(
        it.get("lead_time_days") or it.get("lead_pending") for it in items
    )
    company, contact = quote.deal.company, getattr(quote.deal, "contact", None)
    if grid_enabled():
        return _quote_grid_pdf(
            quote, items=items, optional_items=optional_items, extras=extras, brand=brand, draft=draft, lead=lead
        )
    content: list[dict[str, Any]] = []

    addressee: list[dict[str, Any]] = []
    if company is not None:
        addressee = [_para(_text(company.name, bold=True))]
        from parties.models import Company
        from parties.people import contact_name

        person = contact_name(company) if isinstance(company, Company) else getattr(company, "contact_person", "")
        if person:
            addressee.append(_para(person))
    elif contact is not None:
        addressee = ([_para(contact.position)] if getattr(contact, "position", "") else []) + [
            _para(_text(contact.name or "—", bold=True))
        ]
    if addressee:
        content.append(
            {
                "type": "table",
                "attrs": {"columnWidths": [55, 45], "variant": "plain"},
                "content": [{"type": "tableRow", "content": [_cell([_para()]), _cell(addressee)]}],
            }
        )

    manager = quote.prepared_by
    info = [(_("Действительно до"), _date_text(quote.valid_until) if quote.valid_until else "")]
    if quote.version and quote.version > 1 and not draft:
        info.insert(0, (_("Версия"), str(quote.version)))
    if manager is not None:
        info += [
            (_("Менеджер"), manager.get_full_name() or manager.email),
            (_("Телефон"), getattr(manager, "phone", "") or getattr(seller, "phone", "") or ""),
            (_("Почта"), manager.email or ""),
        ]
    if any(value for _label, value in info):
        content.append(_label_rows(info))

    content += [_para(line) for line in _lines(extras.get("cover_text"))]
    content.append(_quote_lines_table(items, quote, lead=lead, numbered=False))
    content += totals_block(_sums(totals), ccy, lang)

    if optional_items:
        content += [
            {"type": "heading", "attrs": {"level": 3}, "content": [_text(_("Опционально (не входит в итог)"))]},
            _para(_("Позиции ниже предлагаются дополнительно и не включены в сумму «Итого к оплате».")),
            _quote_lines_table(
                [{**it, "display_type": "ITEM"} for it in optional_items], quote, lead=lead, numbered=True
            ),
        ]

    public_url = None if draft else public_quote_url(quote)
    code = "" if draft else (quote.verification_code or "")

    terms = extras.get("quote_terms") or []
    if terms:
        content += [
            {"type": "heading", "attrs": {"level": 3}, "content": [_text(_("Условия поставки"))]},
            _label_rows([(str(row["label"]), str(row["value"])) for row in terms]),
        ]

    if code:
        content += [
            _para(_text(_("ДОКУМЕНТ ОФИЦИАЛЬНО ПОДПИСАН"), bold=True)),
            _para(f"{quote.signatory_name} ({quote.signatory_position})"),
            _para(
                f"{quote.signatory_basis_text or _('на основании Устава')} · {_moment(quote.signed_at)}",
            ),
        ]

    cabinet = (getattr(django_settings, "CABINET_URL", "") or "").rstrip("/")
    verify_url = (f"{cabinet}/v/{code}" if cabinet else None) if code else public_url
    number = quote.number or f"{quote.deal_id}-{quote.version}"
    body = _template_body("", scalars={}, blocks={}, lang=lang)  # пустое тело по контракту (версия, язык, поля)
    body["doc"]["content"] = content
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(
            title=_("Коммерческое предложение"),
            number=number,
            date=_local_date(quote.created_at),
            verification_code=code or None,
            verification_url=verify_url or None,
            # QR отправленного КП ведёт на онлайн-версию, а не на проверку: своя подпись, ссылка с токеном не печатается.
            qr_caption=(
                _(
                    "Онлайн-версия предложения: отсканируйте QR-код, чтобы посмотреть актуальную версию КП; для "
                    "подтверждения свяжитесь с вашим менеджером."
                )
                if verify_url and not code
                else None
            ),
        ),
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf


def _quote_grid_pdf(quote, *, items, optional_items, extras, brand, draft: bool, lead: bool) -> bytes:
    """КП в сетке документа (стандарт §4–§6, план ДОК-4): вид и инфоблок справа, адресат в окне конверта, вводный текст,
    позиции стопкой, итоги с «К оплате», опциональные позиции вне итога, условия парами, отметка подписи и QR."""
    from django.conf import settings as django_settings
    from rt_docs import DocumentMeta, InfoRow, Layout
    from rt_docs.commercial import conditions_block, grid_totals_block
    from rt_docs.pdf import render_pdf

    from crm.services.documents import public_quote_url

    lang = "ru"
    seller, profile = brand.get("seller"), brand.get("seller_profile")
    totals = extras["totals"]
    ccy = totals.get("ccy") or "UZS"
    deal = quote.deal
    company, contact = deal.company, getattr(deal, "contact", None)
    number = quote.number or f"{quote.deal_id}-{quote.version}"
    manager = quote.prepared_by

    info = [
        InfoRow(_("КП №"), number, code=True, role="number"),
        InfoRow(_("Дата"), _date_text(quote.created_at), role="date"),
    ]
    if quote.valid_until:
        info.append(InfoRow(_("Действует до"), _date_text(quote.valid_until)))
    if quote.version and quote.version > 1 and not draft:
        info.append(InfoRow(_("Версия"), str(quote.version)))
    if getattr(deal, "number", ""):
        info.append(InfoRow(_("Заявка"), deal.number, code=True))
    if manager is not None:
        phone = getattr(manager, "phone", "") or getattr(seller, "phone", "") or ""
        info.append(InfoRow(_("Менеджер"), manager.get_full_name() or manager.email))
        if phone:
            info.append(InfoRow(_("Телефон"), phone))
        if manager.email:
            info.append(InfoRow(_("Почта"), manager.email))

    content: list[dict[str, Any]] = [_para(line) for line in _lines(extras.get("cover_text"))]
    content.append(_quote_grid_table(items, quote, lead=lead, numbered=False))
    content += grid_totals_block(_sums(totals), ccy, lang)
    if optional_items:
        content += [
            {"type": "heading", "attrs": {"level": 3}, "content": [_text(_("Опционально (не входит в итог)"))]},
            _quote_grid_table(
                [{**it, "display_type": "ITEM"} for it in optional_items], quote, lead=lead, numbered=True
            ),
        ]
    terms = extras.get("quote_terms") or []
    content += conditions_block([(str(row["label"]), str(row["value"])) for row in terms])

    public_url = None if draft else public_quote_url(quote)
    code = "" if draft else (quote.verification_code or "")
    if code:
        content += [
            _para(_text(f"{quote.signatory_position} {quote.signatory_name}".strip(), bold=True)),
            _note_para(
                _("Подписано электронной подписью %(moment)s · %(basis)s")
                % {"moment": _moment(quote.signed_at), "basis": quote.signatory_basis_text or _("на основании Устава")}
            ),
        ]
    cabinet = (getattr(django_settings, "CABINET_URL", "") or "").rstrip("/")
    verify_url = (f"{cabinet}/v/{code}" if cabinet else None) if code else public_url
    addressee, strong = window_of(company, contact)
    body = _template_body("", scalars={}, blocks={}, lang=lang)
    body["doc"]["content"] = content
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(
            title=_("КП № %(number)s") % {"number": _("без номера") if draft else number},
            kind_label=_("Коммерческое предложение"),
            number=number,
            date=_local_date(quote.created_at),
            addressee=addressee,
            addressee_strong=strong,
            info=tuple(info),
            contact=contact_rows(company, contact),
            verification_code=code or None,
            verification_url=verify_url or None,
            qr_caption=(
                _("Онлайн-версия КП: отсканируйте QR-код, чтобы посмотреть актуальную версию и принять предложение.")
                if verify_url and not code
                else None
            ),
        ),
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf
