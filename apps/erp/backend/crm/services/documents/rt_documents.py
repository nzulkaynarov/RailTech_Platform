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
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.utils.translation import gettext as _


def enabled(kind: str) -> bool:
    """Вид документа рендерится rt_docs (иначе — прежний шаблон Django)."""
    return kind in set(getattr(settings, "RT_DOCS_DOCUMENTS", ()))


def _lines(text: str | None) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def letterhead_of(seller, profile):
    """Бланк продавца для rt_docs: название, адрес, ИНН и банк строками, подвал, логотип, цвет и шрифт профиля."""
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
    font = getattr(profile, "font_family", "") if getattr(profile, "font_family", "") in ("sans", "serif") else "sans"
    return Letterhead(
        company_name=name or "—",
        requisites=tuple(requisites),
        footer=tuple(_lines(getattr(profile, "footer_text", ""))),
        logo=logo,
        **({"accent": accent} if len(accent) == 7 and accent.startswith("#") else {}),
        font=font,
    )


def _bank_lines(seller, profile) -> list[str]:
    details = _lines(getattr(profile, "bank_details", ""))
    if details:
        return details
    account = (getattr(seller, "bank_account", "") or "").strip()
    if not account:
        return []
    mfo = (getattr(seller, "mfo", "") or "").strip()
    return [f"{_('Р/с:')} {account}" + (f" · {_('МФО:')} {mfo}" if mfo else "")]


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


def _template_body(body_html: str, *, scalars: dict[str, Any], blocks: dict[str, Any], lang: str) -> dict[str, Any]:
    """Шаблон ERP (санитизированный `body_html`) → тело rt_docs: скаляры — текстом (экранированы), `{{doc.*}}` блоков —
    узлами-блоками `html_to_body`, данные которых передаются в рендер. Неизвестный код остаётся текстом, как и раньше.
    """
    from django.utils.html import escape
    from rt_docs import html_to_body, load_catalog

    from crm.services.document_placeholders import PLACEHOLDER_RE

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
    blocks: dict[str, Any] = {
        "doc.items_table": items_table(lines, ccy, lang, with_unit=False),
        "doc.totals": totals_block(sums, ccy, lang),
        "doc.payment_requisites": payment_requisites(
            lang, recipient=recipient, inn=inn, bank_lines=_bank_lines(seller, profile), purpose=purpose
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
    head = ([_para("; ".join(refs))] if refs else []) + [_parties(seller, profile, invoice.deal.company)]
    body["doc"]["content"] = head + body["doc"]["content"]
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(title=_("Счёт на оплату"), number=invoice.number, date=_local_date(issued)),
        blocks=blocks,
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf


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
    blocks: dict[str, Any] = {
        "doc.refs": _act_refs(act, invoice),
        "doc.items_table": items_table(
            _item_lines(invoice.items.all() if invoice is not None else []), ccy, lang, with_unit=False
        ),
        "doc.totals": totals_block(_sums(totals), ccy, lang),
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
    body["doc"]["content"] = [_parties(seller, profile, company or contact, _("Покупатель"))] + body["doc"]["content"]
    code = "" if draft else (act.verification_code or "")
    cabinet = (getattr(django_settings, "CABINET_URL", "") or "").rstrip("/")
    result = render_pdf(
        body,
        letterhead=letterhead_of(seller, profile),
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(
            title=_("Акт приёма-передачи"),
            number=act.number,
            date=_local_date(act.issued_at or act.created_at),
            verification_code=code or None,
            verification_url=f"{cabinet}/v/{code}" if code and cabinet else None,
        ),
        blocks=blocks,
        draft=draft,
        highlight_missing=False,
    )
    return result.pdf
