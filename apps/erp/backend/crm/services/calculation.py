"""Расчёт по заявке (D2-1, SPEC-v3 §7.4, путь заявки шаги 3–4).

Расчёт — черновик КП заявки (последняя версия, собранная сотрудником) и его позиции; задание расчёта — проекция
резолюции EDS (`CalcTask`). Здесь — правила экрана «Расчёт» Платформы:

* **Зона строки** — по типу позиции (ADR-0012 п. 6): услуга (карточка каталога `SERVICES` или строка без карточки
  типа «услуга») — зона `services`, право `quote.visa_services`; всё остальное — `goods`, право `quote.visa_goods`.
  Правит, добавляет, удаляет и визирует строку только держатель права её зоны (снабженец не правит услугу,
  гл. инженер — товар); администратор (`is_superuser`) — любую. Кто визирует — факт визы (`CalcLine.visa_by`):
  список «сотрудников зоны» в CRM ещё не появился (B-007), поэтому визирует любой держатель права зоны.
* **Закупка** товара — цена за единицу в валюте строки (`frozen_base_price`); услуги — ставка бригады × дни (их
  вводит гл. инженер, `CalcLine.crew_rate` / `crew_days`), закупка услуги напрямую не правится.
  **Клиенту** — цена без НДС за единицу; из неё считается наценка строки (`margin_percent`), как в движке КП:
  клиенту = себестоимость × (1 + наценка) × (1 − скидка).
* **Виза** снимается любой правкой строки (она подтверждает именно эти цифры). Визировать можно строку с закупкой
  и ценой клиенту.
* **«Расчёт готов»** — только когда завизированы все строки КП, иначе 409 `VISAS_MISSING`: КП уходит на одобрение
  директору в EDS тем же путём, что и после виз КП (`eds_quote_approval.request_director_approval`, событие
  `quote.ready_for_approval` с визами строк).
* Видимость себестоимости (решения архитектора по Q-D2-1-2 и Q-D2-1-4, режет сам ERP): закупку и себестоимость
  строки (у услуги — ставку и дни бригады) видит держатель `quote.view_cost_margin` или права визы зоны этой строки,
  цены поставщика — `quote.view_cost_margin` или зона товаров; наценку, итоги себестоимости и наценки и порог маржи
  резолюции — только `quote.view_cost_margin`. Бухгалтер — цены клиенту и итоги без себестоимости.

Ошибки — `CalcError(code, status)`; вьюхи отдают `{"detail": code}`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from django.db import DataError, transaction
from django.db.models import Max, Q
from django.utils import timezone
from parties import test_companies
from sales.services import deal_numbers

from accounts.constants import Permission
from accounts.services.permissions import is_seller, member_has_permission
from catalog.item_ref import item_ref, main_photos
from core.currency import BASE_CURRENCY, line_amount
from core.quantity import as_qty, to_qty
from crm.services._plural import pluralize_ru

from ..constants import DealStageCode, QuoteStatusCode
from ..models import ActivityLog, CalcLine, CalcLineKind, CalcPriceBasis, CalcTask
from ..models import CalcZone as Zone
from ..models import Deal, Quote, QuoteItem

logger = logging.getLogger(__name__)

ZONE_PERMISSION = {Zone.GOODS: Permission.QUOTE_VISA_GOODS.value, Zone.SERVICES: Permission.QUOTE_VISA_SERVICES.value}
#: Стадии сделки, в которых заявка «в расчёте» (список «Заявки в расчёте»); `all` добавляет ушедшие дальше.
OPEN_STAGES = (DealStageCode.SOURCING, DealStageCode.CALCULATING)
#: Индикаторы виз заявки (SPEC-v3 §7.4): товары со склада, товары под заказ, услуги.
VISA_GROUPS = ("stock", "supply", "engineer")
MAX_LINES_PER_CALL = 50
MAX_ROWS = 300
_CENT = Decimal("0.01")
_MARKUP_MAX = Decimal("500")


class CalcError(Exception):
    def __init__(self, code: str, status: int = 409, **extra: Any) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.extra = extra


# ── права ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _own_company_id() -> Optional[int]:
    from core.tenant import own_company_id

    return own_company_id()


def has_perm(user, perm: str) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    company_id = _own_company_id()
    return bool(company_id) and member_has_permission(user, company_id, perm)


def zone_rights(user) -> dict[str, bool]:
    return {zone: has_perm(user, perm) for zone, perm in ZONE_PERMISSION.items()}


def _require_staff(user) -> None:
    if not (getattr(user, "is_superuser", False) or is_seller(user)):
        raise CalcError("BACKOFFICE_ONLY", 403)


def _require_zone(user, zone: str) -> None:
    if not has_perm(user, ZONE_PERMISSION[zone]):
        raise CalcError("ZONE_NOT_PERMITTED", 403, zone=zone)


def _require(user, perm: str) -> None:
    if not has_perm(user, perm):
        raise CalcError("ROLE_NOT_PERMITTED", 403)


def person_name(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.email or "").strip() or f"Сотрудник #{user.pk}"


# ── строки ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def calc_of(item: QuoteItem) -> Optional[CalcLine]:
    try:
        return item.calc
    except CalcLine.DoesNotExist:
        return None


def zone_of(item: QuoteItem) -> str:
    """Зона строки: услуга по карточке каталога или по типу строки без карточки — `services`, иначе `goods`."""
    if item.product_id:
        return Zone.SERVICES if item.product.is_service else Zone.GOODS
    calc = calc_of(item)
    return Zone.SERVICES if calc is not None and calc.kind == CalcLineKind.SERVICE else Zone.GOODS


def _own_offers(product_ids: Iterable[int]) -> dict[int, Any]:
    """Своё предложение (склад компании): `SupplierOffer` своей компании — остаток и срок со склада."""
    from catalog.models import SupplierOffer

    ids = [pid for pid in set(product_ids) if pid]
    company_id = _own_company_id()
    if not ids or not company_id:
        return {}
    found: dict[int, Any] = {}
    for offer in SupplierOffer.objects.filter(product_id__in=ids, supplier_id=company_id, is_active=True).order_by(
        "product_id", "-stock_quantity"
    ):
        found.setdefault(offer.product_id, offer)
    return found


def _supplier_offers(product_ids: Iterable[int]) -> dict[int, Any]:
    """Лучшее предложение внешнего поставщика (не своей компании): действующее, самое дешёвое."""
    from catalog.models import SupplierOffer

    ids = [pid for pid in set(product_ids) if pid]
    if not ids:
        return {}
    today = timezone.localdate()
    offers = (
        SupplierOffer.objects.filter(product_id__in=ids, is_active=True)
        .exclude(supplier_id=_own_company_id())
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related("supplier", "currency")
        .order_by("product_id", "base_price")
    )
    found: dict[int, Any] = {}
    for offer in offers:
        found.setdefault(offer.product_id, offer)
    return found


def line_supplier_offer(item: QuoteItem, suppliers: Optional[dict[int, Any]] = None):
    """Предложение поставщика строки-товара: выбранное в расчёте (`item.offer`, внешний поставщик), иначе лучшее
    действующее — то же, что колонка «Поставщик · срок». Услуга или строка без карточки — None. `suppliers` — уже
    подгруженные `_supplier_offers` (экран расчёта), иначе запрос по одной строке."""
    if item.offer_id and item.offer.supplier_id != _own_company_id():
        return item.offer
    if not item.product_id or zone_of(item) != Zone.GOODS:
        return None
    found = suppliers if suppliers is not None else _supplier_offers([item.product_id])
    return found.get(item.product_id)


def supplier_lead_days(offer, quantity: int) -> Optional[int]:
    """Срок поставщика на `quantity` единиц: его наличие покрывает — срок со склада поставщика, иначе — под заказ (поля
    `SupplierOffer`: «stock_quantity за in_stock_lead_time_days, остальное за order_lead_time_days»). Нет данных — None.
    """
    if offer is None:
        return None
    if offer.stock_quantity and offer.stock_quantity >= quantity and offer.in_stock_lead_time_days:
        return offer.in_stock_lead_time_days
    return offer.order_lead_time_days or offer.in_stock_lead_time_days or None


def _money(value: Any) -> Optional[str]:
    if value is None:
        return None
    return f"{Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP):.2f}"


def _markup(cost: Decimal, price: Decimal) -> Optional[str]:
    if cost is None or cost <= 0:
        return None
    return f"{((price - cost) / cost * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}"


@dataclass
class _Context:
    own: dict[int, Any] = field(default_factory=dict)
    suppliers: dict[int, Any] = field(default_factory=dict)
    #: Склад (D2-2): остаток, резервы проектов и ячейки по товарам; резерв по строкам расчёта.
    stock: dict[int, Any] = field(default_factory=dict)
    reserved: dict[int, int] = field(default_factory=dict)
    #: Главное фото карточек строк (ЕД-4): одна выборка на расчёт.
    photos: dict[int, int] = field(default_factory=dict)


def _context(items: list[QuoteItem]) -> _Context:
    from inventory.services import stock

    ids = [it.product_id for it in items if it.product_id]
    return _Context(
        own=_own_offers(ids),
        suppliers=_supplier_offers(ids),
        stock=stock.availability(ids),
        reserved=stock.reserved_by_item(it.pk for it in items),
        photos=main_photos(ids),
    )


def _stock_of(item: QuoteItem, ctx: _Context) -> Optional[dict]:
    """Склад по строке-товару: на складе всего, свободно (после резервов), зарезервировано за этой строкой, ячейка и сколько
    строка может взять (`available`). Учёт движений есть (D2-2) — остаток оттуда; нет — прежнее поведение D2-1: наличие из
    своего предложения (`SupplierOffer.stock_quantity`). Строка без карточки каталога — None (склада у неё нет)."""
    if not item.product_id:
        return None
    reserved = ctx.reserved.get(item.pk, 0)
    state = ctx.stock.get(item.product_id)
    if state is not None and state.tracked:
        return {
            "on_hand": state.on_hand,
            "free": state.free,
            "reserved": reserved,
            "cell": state.main_cell,
            "available": state.free + reserved,
        }
    own = ctx.own.get(item.product_id)
    on_hand = own.stock_quantity if own is not None else 0
    return {"on_hand": on_hand, "free": on_hand, "reserved": 0, "cell": None, "available": on_hand}


def _line_kind(item: QuoteItem, zone: str, ctx: _Context) -> tuple[str, Optional[int]]:
    """Тип для экрана: услуга; товар со склада (свободный остаток покрывает количество); товар под заказ."""
    if zone == Zone.SERVICES:
        return "service", None
    info = _stock_of(item, ctx)
    on_hand = info["on_hand"] if info is not None else None
    if info is not None and info["available"] >= item.quantity and info["available"] > 0:
        return "goods", on_hand
    return "goods_to_order", on_hand


#: Пометка КП, когда срок дефицитной части неизвестен (нет предложения поставщика со сроком): в «Условиях поставки» КП —
#: «Сроки поставки: …уточняется», в договоре — «в сроки, согласованные Сторонами» (`Quote.delivery_lead_time_days` = 0).
LEAD_PENDING_NOTE = "Срок поставки позиций под заказ уточняется"


def delivery_lead(item: QuoteItem, ctx: _Context) -> Optional[int]:
    """Срок строки для КП и договора (D26G-8): максимум из срока «со склада» и срока поставщика на дефицитную часть.

    Свободный остаток (с резервом этой строки) покрывает количество — срок строки как есть (со склада или введённый
    снабженцем). Дефицит — срок поставщика на недостающее (`supplier_lead_days`), но не меньше срока строки. Срока
    поставщика нет: срок, введённый снабженцем (отличный от срока «со склада» своего предложения), считается данными;
    иначе — None («срок уточняется»). Логистика в данных отдельно не хранится — входит в срок поставщика."""
    current = item.lead_time_days or 0
    if zone_of(item) != Zone.GOODS or not item.product_id:
        return current
    info = _stock_of(item, ctx)
    available = max(info["available"], 0) if info is not None else 0
    if available >= item.quantity:
        return current
    supplier = supplier_lead_days(line_supplier_offer(item, ctx.suppliers), item.quantity - available)
    if supplier:
        return max(current, supplier)
    own = ctx.own.get(item.product_id)
    stock_lead = own.in_stock_lead_time_days if own is not None else 0
    if current and current != stock_lead:
        return current
    return None


def apply_delivery_leads(quote: Quote, items: list[QuoteItem]) -> list[int]:
    """«Расчёт готов»: срок строк-товаров пересчитывается по складу и поставщику (`delivery_lead`). Пишется прямо в базу
    (`update`), без новой версии строки — визы остаются. Строки с неизвестным сроком получают 0, а КП — пометку
    `LEAD_PENDING_NOTE` и общий срок 0 (если срок КП и пометку не задали руками); данные появились при повторном
    «Расчёт готов» — пометка снимается. Вернуть id строк с неизвестным сроком."""
    ctx = _context(items)
    pending: list[int] = []
    for item in items:
        lead = delivery_lead(item, ctx)
        if lead is None:
            pending.append(item.pk)
            lead = 0
        if lead != (item.lead_time_days or 0):
            QuoteItem.objects.filter(pk=item.pk).update(lead_time_days=lead)
            item.lead_time_days = lead
    ours = quote.delivery_note == LEAD_PENDING_NOTE and quote.delivery_lead_time_days == 0
    if pending and quote.delivery_lead_time_days is None and not quote.delivery_note:
        quote.delivery_lead_time_days, quote.delivery_note = 0, LEAD_PENDING_NOTE
        quote.save(update_fields=["delivery_lead_time_days", "delivery_note", "updated_at"])
    elif not pending and ours:
        quote.delivery_lead_time_days, quote.delivery_note = None, ""
        quote.save(update_fields=["delivery_lead_time_days", "delivery_note", "updated_at"])
    return pending


def _visa_group(kind: str) -> str:
    return {"goods": "stock", "goods_to_order": "supply", "service": "engineer"}[kind]


def is_signed(item: QuoteItem, calc: Optional[CalcLine] = None) -> bool:
    """Виза действует, если поставлена в зоне строки и строка с тех пор не менялась (версия `QuoteItem` та же —
    правку через любой путь, в том числе старый `crm/quote-items`, виза не переживает)."""
    calc = calc if calc is not None else calc_of(item)
    return (
        calc is not None
        and calc.visa_at is not None
        and calc.visa_zone == zone_of(item)
        and calc.visa_item_version == item.version
    )


def _stock_payload(item: QuoteItem, zone: str, ctx: _Context, on_hand: Optional[int]) -> dict:
    """Колонка «Склад»: на складе, свободно, ячейка, зарезервировано за строкой (D2-2, B-D21-1)."""
    info = _stock_of(item, ctx) if zone == Zone.GOODS else None
    if info is None:
        return {"on_hand": on_hand, "free": None, "cell": None, "reserved": None}
    return {"on_hand": info["on_hand"], "free": info["free"], "cell": info["cell"], "reserved": info["reserved"]}


def line_payload(item: QuoteItem, ctx: _Context, *, show_cost: bool, rights: dict[str, bool], editable: bool) -> dict:
    """Строка расчёта. Видимость себестоимости (решение архитектора по Q-D2-1-2): закупку и себестоимость строки
    видит держатель `quote.view_cost_margin` или права визы зоны этой строки (гл. инженер — ставку и дни бригады своих
    услуг, снабженец — закупку и цены поставщика своих товаров); наценку — только `quote.view_cost_margin`."""
    zone = zone_of(item)
    kind, on_hand = _line_kind(item, zone, ctx)
    calc = calc_of(item)
    zone_cost = show_cost or rights.get(zone, False)
    offer_visible = show_cost or rights.get(Zone.GOODS, False)
    supplier = None
    offer = line_supplier_offer(item, ctx.suppliers)
    if offer is not None:
        supplier = {
            "name": offer.supplier.name,
            "lead_days": offer.order_lead_time_days or offer.in_stock_lead_time_days or None,
            "min_order_qty": offer.min_order_qty,
            "price_valid_until": offer.valid_until.isoformat() if offer.valid_until else None,
            "offer_price": _money(offer.base_price) if offer_visible else None,
            "offer_currency": (offer.currency.code if offer.currency_id else None) if offer_visible else None,
        }
    product = item.product if item.product_id else None
    services = zone == Zone.SERVICES
    return {
        "id": item.id,
        "position": item.position,
        "name": item.imported_raw_name or (product.name if product else "") or f"Позиция #{item.id}",
        "article": item.mpn
        or (product.manufacturer_part_number if product else "")
        or (product.sku if product else ""),
        "product_id": item.product_id,
        "product_name": product.name if product else None,
        # Черновик карточки (ADR-0027): строку ещё можно сопоставить с опубликованной позицией каталога.
        "product_draft": bool(product is not None and getattr(product.status, "code", None) == "DRAFT"),
        # СЦ-10: строка без карточки похожа на карточку каталога — «Выбрать» или «Новая позиция».
        "catalog_hint": (
            {"id": calc.catalog_hint_id, "name": calc.catalog_hint.name}
            if calc is not None and calc.catalog_hint_id and not item.product_id
            else None
        ),
        "item": item_ref(product, ctx.photos),
        "kind": kind,
        "zone": zone,
        "quantity": item.quantity,
        "unit": item.unit,
        "unit_code": item.unit_code or None,
        "stock": _stock_payload(item, zone, ctx, on_hand),
        "supplier": supplier,
        "lead_days": item.lead_time_days or None,
        "purchase_price": _money(item.frozen_base_price) if zone_cost and not services else None,
        "purchase_currency": (
            (
                (item.frozen_currency.code if item.frozen_currency_id else BASE_CURRENCY)
                if not services
                else BASE_CURRENCY
            )
            if zone_cost
            else None
        ),
        "crew_rate": (
            _money(calc.crew_rate)
            if zone_cost and services and calc is not None and calc.crew_rate is not None
            else None
        ),
        "crew_days": (
            str(calc.crew_days) if zone_cost and services and calc is not None and calc.crew_days is not None else None
        ),
        "cost": _money(item.landed_cost) if zone_cost else None,
        "client_price": _money(item.final_price_excl_vat),
        "markup_pct": _markup(item.landed_cost, item.final_price_excl_vat) if show_cost else None,
        "visa": (
            {
                "by": calc.visa_by_name or person_name(calc.visa_by),
                "at": calc.visa_at.isoformat(),
            }
            if is_signed(item, calc)
            else None
        ),
        "group": _visa_group(kind),
        "can_edit": editable and rights.get(zone, False),
    }


# ── заявка, КП, задание ────────────────────────────────────────────────────────────────────────────────────────────


def _deal_or_404(deal_id: int) -> Deal:
    deal = Deal.objects.select_related("company", "stage", "manager", "assigned_to").filter(pk=deal_id).first()
    if deal is None:
        raise CalcError("DEAL_NOT_FOUND", 404)
    return deal


def _locked_deal_or_404(deal_id: int) -> Deal:
    """Заявка под блокировкой строки — только внутри транзакции («Расчёт готов»)."""
    deal = (
        Deal.objects.select_for_update(of=("self",))
        .select_related("company", "stage", "manager", "assigned_to")
        .filter(pk=deal_id)
        .first()
    )
    if deal is None:
        raise CalcError("DEAL_NOT_FOUND", 404)
    return deal


def latest_task(deal_id: int) -> Optional[CalcTask]:
    return CalcTask.objects.filter(deal_id=deal_id).order_by("-decided_at", "-id").first()


def _task_or_404(deal: Deal) -> CalcTask:
    task = latest_task(deal.id)
    if task is None:
        raise CalcTaskMissing()
    return task


class CalcTaskMissing(CalcError):
    def __init__(self) -> None:
        super().__init__("CALC_TASK_NOT_FOUND", 404)


def calc_quote(deal: Deal) -> Optional[Quote]:
    """КП расчёта: последняя версия, собранная сотрудником (у «КП заявки» прежних сделок исполнителя нет)."""
    return (
        Quote.objects.filter(deal=deal, prepared_by__isnull=False)
        .select_related("status", "quote_currency")
        .order_by("-version")
        .first()
    )


def _draft_or_409(deal: Deal, *, lock: bool = True) -> Quote:
    from .quotes.editable import quote_edit_lock_code

    quote = calc_quote(deal)
    if quote is None:
        raise CalcError("CALC_NOT_STARTED", 409)
    if deal.stage_id and deal.stage.code in EDIT_LOCKED_STAGES:
        # закрытая заявка и заявка, ушедшая дальше расчёта, — только просмотр (ЗАЯВ-1)
        raise CalcError("DEAL_NOT_IN_CALCULATION", 409, stage=deal.stage.code)
    if lock:
        quote = Quote.objects.select_for_update(of=("self",)).select_related("status", "deal").get(pk=quote.pk)
    code = quote_edit_lock_code(quote)
    if code:
        raise CalcError(code, 409)
    return quote


def _calc_state(quote: Optional[Quote]) -> str:
    """Где расчёт: не начат; в работе; у директора; возвращён директором; отправлен клиенту и дальше."""
    if quote is None:
        return "not_started"
    code = quote.status.code if quote.status_id else QuoteStatusCode.DRAFT
    if code == QuoteStatusCode.DRAFT:
        return "returned" if quote.director_decision == "return" else "in_progress"
    if code in (QuoteStatusCode.PENDING_APPROVAL, QuoteStatusCode.PENDING_TRADE_REVIEW):
        return "at_director"
    if code == QuoteStatusCode.REJECTED:
        return "rejected"
    return "approved"


def _rejection(quote: Optional[Quote]) -> tuple[Optional[str], Optional[str]]:
    """Кто отклонил КП и почему (D26G-3): директор в EDS (решение `reject`, комментарий) или клиент (кабинет, бот,
    офлайн — `client_reject_reason`). Не отклонено — (None, None)."""
    if quote is None or _calc_state(quote) != "rejected":
        return None, None
    if quote.director_decision == "reject":
        return "director", quote.director_comment or None
    return "client", quote.client_reject_reason or None


def _can_revise(deal: Deal, quote: Optional[Quote], user) -> bool:
    """«Новая версия КП» и «Отказ по заявке» после отказа клиента: заявка вернулась в расчёт, право `quote.build`."""
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    return _rejection(quote)[0] == "client" and stage in OPEN_STAGES and has_perm(user, Permission.QUOTE_BUILD.value)


def _billable(quote: Optional[Quote]) -> list[QuoteItem]:
    if quote is None:
        return []
    return list(
        quote.items.billable()
        .select_related(
            "product__domain_type", "product__status", "frozen_currency", "offer__supplier", "offer__currency", "calc"
        )
        .select_related("calc__visa_by", "calc__catalog_hint")
        .order_by("position", "id")
    )


def _groups(items: list[QuoteItem], ctx: _Context) -> dict[str, dict]:
    """Индикаторы виз: по каждой группе — нужна ли, сколько строк подписано, кто подписывал (по факту визы)."""
    out = {name: {"state": "none", "total": 0, "signed": 0, "by": []} for name in VISA_GROUPS}
    for item in items:
        zone = zone_of(item)
        kind, _ = _line_kind(item, zone, ctx)
        group = out[_visa_group(kind)]
        group["total"] += 1
        calc = calc_of(item)
        if is_signed(item, calc):
            group["signed"] += 1
            name = calc.visa_by_name or person_name(calc.visa_by)
            if name and name not in group["by"]:
                group["by"].append(name)
    for group in out.values():
        if group["total"]:
            group["state"] = "done" if group["signed"] == group["total"] else "waiting"
    return out


def _assignees(task: CalcTask) -> list[dict]:
    rows = []
    for assignee in task.assignees.select_related("user").order_by("id"):
        rows.append(
            {
                "crm_user_id": assignee.crm_user_id,
                "zone": assignee.zone,
                "name": person_name(assignee.user) if assignee.user_id else None,
            }
        )
    return rows


def _deal_brief(deal: Deal) -> dict:
    return {
        "id": deal.id,
        "number": deal.number or None,
        "title": deal.title,
        "created_at": deal.created_at.isoformat(),
        "stage_code": deal.stage.code if deal.stage_id else DealStageCode.DRAFT,
        "client_name": deal.company.name if deal.company_id else None,
        "manager_name": person_name(deal.manager) if deal.manager_id else None,
        **test_companies.flag(deal.company if deal.company_id else None),
    }


def _task_brief(task: CalcTask, *, show_cost: bool = False) -> dict:
    """Задание из резолюции; порог маржи — только держателю `quote.view_cost_margin` (Q-D2-1-2)."""
    return {
        "letter_number": task.letter_number,
        "letter_subject": task.letter_subject,
        "resolution_text": task.resolution_text,
        "decided_at": task.decided_at.isoformat(),
        "decided_by_name": task.decided_by_name or None,
        "due": task.due.isoformat(),
        "min_margin_pct": (None if task.min_margin_pct is None or not show_cost else f"{task.min_margin_pct:.2f}"),
    }


# ── список «Заявки в расчёте» ──────────────────────────────────────────────────────────────────────────────────────


def _mapped_crm_ids(user) -> set[int]:
    from integration.models import CrmUserMapping

    return set(CrmUserMapping.objects.filter(user=user).values_list("crm_user_id", flat=True))


#: «Закрытые» в реестре заявок: КП ушло клиенту, стала проектом (договор, исполнено) или закрыта с причиной.
CLOSED_STAGES = (
    DealStageCode.QUOTE_SENT,
    DealStageCode.CONTRACT_SIGNED,
    DealStageCode.CLOSED_WON,
    DealStageCode.CLOSED_LOST,
)
#: Правка строк и условий закрыта: проект, закрытая заявка. QUOTE_SENT сюда не входит — после замечаний клиента менеджер пересчитывает
#: цену (отправленное КП защищает `quote_edit_lock_code`).
EDIT_LOCKED_STAGES = (DealStageCode.CONTRACT_SIGNED, DealStageCode.CLOSED_WON, DealStageCode.CLOSED_LOST)
STATE_FILTERS = ("open", "closed", "all")
PAGE_MAX = 200


def _crm_client_id(deal: Deal) -> Optional[int]:
    """Клиент CRM компании заявки (сопоставление ERP↔CRM) — «Создать по образцу» открывает форму на нём."""
    from integration.models import CrmClientMapping

    if not deal.company_id:
        return None
    return CrmClientMapping.objects.filter(company_id=deal.company_id).values_list("crm_client_id", flat=True).first()


def _task_row(task: CalcTask) -> dict:
    deal = task.deal
    quote = calc_quote(deal)
    items = _billable(quote)
    ctx = _context(items)
    groups = _groups(items, ctx)
    rejected_by, reject_reason = _rejection(quote)
    return {
        "deal": _deal_brief(deal),
        "letter_number": task.letter_number,
        "due": task.due.isoformat(),
        "state": _calc_state(quote),
        "rejected_by": rejected_by,
        "reject_reason": reject_reason,
        "lines": len(items),
        "visas": {name: groups[name]["state"] for name in VISA_GROUPS},
        "assignees": _assignees(task),
    }


def list_tasks_page(
    user, *, mine: bool = False, state: str = "open", q: str = "", limit: int = MAX_ROWS, offset: int = 0
) -> tuple[list[dict], int]:
    """Реестр заявок (ЗАЯВ-1): `state` — open (в расчёте), closed (КП ушло, проект, закрыта), all; `q` — номер, клиент,
    тема, письмо, текст заявки; страница `limit`/`offset`, второй элемент — всего подходящих. Права те же, что у списка
    «Заявки в расчёте»: любой сотрудник; чужих закрытых заявок прав не прибавляет ни `state`, ни `q`. Скрытые «Ошибка»
    и «Тест» не показываются (открываются по номеру)."""
    _require_staff(user)
    if state not in STATE_FILTERS:
        state = "open"
    limit = max(1, min(int(limit), PAGE_MAX))
    offset = max(0, int(offset))
    latest_ids = CalcTask.objects.values("deal_id").annotate(last=Max("id")).values("last")
    tasks = CalcTask.objects.filter(pk__in=latest_ids).select_related("deal__company", "deal__stage", "deal__manager")
    tasks = test_companies.hide(tasks, "deal__company")  # ТЕСТ-1: заявки тестовых компаний не в реестре и очереди
    if state == "open":
        tasks = tasks.filter(deal__stage__code__in=OPEN_STAGES)
    else:
        tasks = tasks.filter(deal__hidden_in_lists=False)
        if state == "closed":
            tasks = tasks.filter(deal__stage__code__in=CLOSED_STAGES)
    if mine:
        crm_ids = _mapped_crm_ids(user)
        tasks = tasks.filter(Q(assignees__user=user) | Q(assignees__crm_user_id__in=crm_ids)).distinct()
    needle = (q or "").strip()
    if needle:
        cond = (
            Q(deal__number__icontains=needle)
            | Q(deal__title__icontains=needle)
            | Q(deal__company__name__icontains=needle)
            | Q(letter_number__icontains=needle)
            | Q(letter_subject__icontains=needle)
            | Q(deal__notes__icontains=needle)
            | Q(deal__portal_summary__text__icontains=needle)
        )
        parsed = deal_numbers.parse_query(needle)
        if parsed is not None:
            cond |= Q(deal__number_year=parsed[0], deal__number_seq=parsed[1])
        tasks = tasks.filter(cond)
    ordering = ("due", "deal_id") if state == "open" else ("-deal_id",)
    tasks = tasks.order_by(*ordering)
    total = tasks.count()
    page = list(tasks[offset : offset + limit])
    from integration.models import CrmClientMapping

    clients = dict(
        CrmClientMapping.objects.filter(
            company_id__in={t.deal.company_id for t in page if t.deal.company_id}
        ).values_list("company_id", "crm_client_id")
    )
    rows = []
    for task in page:
        row = _task_row(task)
        row["crm_client_id"] = clients.get(task.deal.company_id)
        rows.append(row)
    return rows, total


def list_tasks(user, *, mine: bool = False, scope: str = "open") -> list[dict]:
    """Заявки с заданием расчёта: последняя резолюция каждой, срок, индикаторы виз, ответственный.

    `scope=open` — заявки на стадиях «Расчёт» (подбор, расчёт); `all` — все с заданием (адресация карточки по
    номеру). `mine` — где сотрудник исполнитель резолюции (по пользователю ERP или его `crm_user_id`)."""
    rows, _ = list_tasks_page(user, mine=mine, state="all" if scope == "all" else "open", limit=MAX_ROWS)
    return rows


MAX_REFS = 5000


def deal_refs(user, number: str = "", *, any_request: bool = False) -> list[dict]:
    """Лёгкий справочник заявок с заданием расчёта (без КП, строк и виз): id, номер ЗВ/ПР (`Deal.number`, ERP-09),
    дата создания, стадия — для поиска заявки по номеру в BFF. `number` — отбор по номеру (`ЗВ-2026-104`, `ПР-2026-104`,
    `zv 2026 104` — один NNN года, префикс не важен: после принятия КП заявка становится проектом с тем же NNN); не номер —
    пусто. С новых заявок."""
    _require_staff(user)
    # `any_request` — и заявка без задания расчёта (черновик из передачи лида): у неё есть карточка «Закрыть заявку»
    rows = Deal.objects.all() if any_request else Deal.objects.filter(calc_tasks__isnull=False)
    if number:
        parsed = deal_numbers.parse_query(number)
        if parsed is None:
            return []
        rows = rows.filter(number_year=parsed[0], number_seq=parsed[1])
    rows = rows.distinct().order_by("-id").values("id", "number", "created_at", "stage__code")[:MAX_REFS]
    return [
        {
            "id": row["id"],
            "number": row["number"] or None,
            "created_at": row["created_at"].isoformat(),
            "stage_code": row["stage__code"] or "DRAFT",
        }
        for row in rows
    ]


# ── экран расчёта ──────────────────────────────────────────────────────────────────────────────────────────────────


def _terms(quote: Quote, items: list[QuoteItem]) -> dict:
    """Условия КП для экрана расчёта (FR-16): то, что клиент увидит в КП, PDF и кабинете."""
    lines = [it.lead_time_days or 0 for it in items if it.display_type == QuoteItem.DisplayType.ITEM]
    return {
        "payment_terms": quote.payment_terms or None,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "delivery_days": quote.delivery_lead_time_days,
        "delivery_days_lines": max(lines, default=0),
        "delivery_note": quote.delivery_note or None,
    }


def sheet(deal_id: int, user) -> dict:
    """Экран «Расчёт по заявке»: заявка, задание, КП, строки, итоги без НДС, визы, готовность."""
    _require_staff(user)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    return _sheet(deal, task, user)


def _sheet(deal: Deal, task: CalcTask, user) -> dict:
    from .draft_quote import deal_request_files, deal_request_lines_count, deal_request_text
    from .quotes.editable import quote_edit_lock_code

    quote = calc_quote(deal)
    items = _billable(quote)
    ctx = _context(items)
    show_cost = has_perm(user, Permission.QUOTE_VIEW_COST_MARGIN.value)
    rights = zone_rights(user)
    editable = quote is not None and quote_edit_lock_code(quote) is None
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    # Закрытая заявка и заявка вне расчёта открываются на просмотр: кнопок правки у строк нет (ЗАЯВ-1)
    lines = [
        line_payload(it, ctx, show_cost=show_cost, rights=rights, editable=editable and stage in OPEN_STAGES)
        for it in items
    ]
    purchase = sum((it.landed_cost * it.quantity for it in items), Decimal("0"))
    client = sum((line_amount(it.final_price_excl_vat, it.quantity) for it in items), Decimal("0"))
    groups = _groups(items, ctx)
    missing = sum(1 for line in lines if line["visa"] is None)
    if quote is None:
        blocker = "not_started"
    elif stage not in OPEN_STAGES and editable:
        # Заявка закрыта, проиграна или ушла дальше расчёта: «Расчёт готов» не отправит (409 DEAL_NOT_IN_CALCULATION).
        blocker = "not_in_calculation"
    elif not editable:
        blocker = "not_draft"
    elif not lines:
        blocker = "no_lines"
    elif missing:
        blocker = "visas_missing"
    else:
        blocker = None
    rejected_by, reject_reason = _rejection(quote)
    return {
        "deal": _deal_brief(deal),
        "task": {**_task_brief(task, show_cost=show_cost), "assignees": _assignees(task)},
        "request": {
            "text": deal_request_text(deal),
            "lines": deal_request_lines_count(deal),
            "files": deal_request_files(deal),
            "files_pending": bool(task.request_file_pending),
            "crm_client_id": _crm_client_id(deal),
        },
        "quote": (
            None
            if quote is None
            else {
                "id": quote.id,
                "version": quote.version,
                "number": quote.number or None,
                "state": _calc_state(quote),
                "director_comment": quote.director_comment or None,
                "rejected_by": rejected_by,
                "reject_reason": reject_reason,
                "can_revise": _can_revise(deal, quote, user),
                "vat_rate": f"{quote.vat_rate:.2f}",
                "terms": _terms(quote, items),
            }
        ),
        "lines": lines,
        # Итоги себестоимости и наценки по заявке — только `quote.view_cost_margin` (Q-D2-1-2, Q-D2-1-4).
        "totals": {
            "purchase": _money(purchase) if show_cost else None,
            "client": _money(client),
            "markup_pct": _markup(purchase, client) if show_cost else None,
            "vat_included": False,
        },
        "visas": {name: groups[name] for name in VISA_GROUPS},
        "ready": {"allowed": blocker is None, "blocker": blocker, "missing": missing},
        "close": close_state(deal, user),
        "rights": {
            "goods": rights[Zone.GOODS],
            "services": rights[Zone.SERVICES],
            "build": has_perm(user, Permission.QUOTE_BUILD.value),
            "cost": show_cost,
            "stock": has_perm(user, Permission.SUPPLY_MANAGE.value),
        },
    }


# ── начать расчёт ──────────────────────────────────────────────────────────────────────────────────────────────────


def start(deal_id: int, user) -> dict:
    """Черновик КП расчёта из строк заявки (без ИИ: точные совпадения ГОСТ/артикула, цены своего предложения).
    Уже есть КП расчёта — без изменений."""
    from .draft_quote import prepare_quote_from_request

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    if calc_quote(deal) is None:
        with transaction.atomic():
            Deal.objects.select_for_update(of=("self",)).filter(pk=deal.pk).first()
            if calc_quote(deal) is None:
                _quote, err, _prefilled = prepare_quote_from_request(deal.id, user)
                if err == "NO_REQUEST_LINES":
                    _empty_draft(deal, user)
                elif err:
                    raise CalcError(
                        err, 403 if err.startswith("ONLY_") or err.endswith("_REQUIRED_FOR_ACTION") else 409
                    )
                ActivityLog.objects.create(
                    action="Расчёт начат",
                    detail=f"Черновик КП расчёта по {task.label}",
                    user=user,
                    level="INFO",
                    entity_type="deal",
                    entity_id=deal.id,
                    deal=deal,
                    company_id=deal.company_id,
                    event_code="calc.started",
                    event_params={"letter_number": task.label},
                )
                _link_catalog(calc_quote(deal))
    return _sheet(deal, task, user)


def _empty_draft(deal: Deal, user) -> Quote:
    """Заявка без строк (передача из CRM — только текст): пустой черновик, строки — вручную или ИИ-разбором."""
    from accounts.models import Company
    from accounts.services.permissions import primary_seller_company_id

    from ..models import QuoteStatus
    from .quotes import apply_company_quote_defaults

    company_id = primary_seller_company_id(user) or _own_company_id()
    version = (deal.quotes.aggregate(max_v=Max("version"))["max_v"] or 0) + 1
    quote = Quote.objects.create(
        deal=deal,
        version=version,
        prepared_by=user,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT),
        seller_company_id=company_id,
    )
    if company_id:
        apply_company_quote_defaults(quote, Company.objects.filter(pk=company_id).first())
    return quote


# ── правка строк ───────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class LineInput:
    name: str
    quantity: Decimal = Decimal("1")
    unit: str = ""
    unit_code: str = ""
    kind: str = CalcLineKind.GOODS
    product_id: Optional[int] = None
    article: str = ""
    note: str = ""


def _quantity(value) -> Decimal:
    """Количество строки (ADR-0027 п. 9): до трёх знаков после запятой, не меньше 0,001; пустое — 1."""
    amount = to_qty(value if value not in (None, "") else 1)
    return amount if amount > 0 else Decimal("1")


def _unit(code: str) -> tuple[str, str]:
    """Единица из справочника (ADR-0027 п. 10): код и русское название; неизвестный код — отказ."""
    from master_data.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.filter(code__iexact=(code or "").strip()).first()
    if unit is None:
        raise CalcError("UNIT_NOT_FOUND", 400)
    return unit.code, unit.name[:32]


def _product(product_id: Optional[int]):
    from catalog.models import Product

    if not product_id:
        return None
    product = Product.objects.select_related("domain_type", "uom").filter(pk=product_id).first()
    if product is None:
        raise CalcError("PRODUCT_NOT_FOUND", 400)
    return product


def _currency(code: Optional[str]):
    from master_data.models import Currency

    if not code:
        return None
    currency = Currency.objects.filter(code=code.upper()).first()
    if currency is None:
        raise CalcError("BAD_CURRENCY", 400)
    return currency


def _prefill_from_offer(item: QuoteItem, product) -> None:
    """Закупка и срок по карточке: своё предложение (склад), иначе лучший внешний поставщик."""
    if product is None or item.frozen_base_price:
        return
    own = _own_offers([product.id]).get(product.id)
    offer = own if own is not None and own.base_price > 0 else _supplier_offers([product.id]).get(product.id)
    if offer is None:
        return
    item.frozen_base_price = offer.base_price
    if offer.currency_id:
        item.frozen_currency_id = offer.currency_id
    if offer.supplier_id != _own_company_id():
        item.offer = offer
    item.lead_time_days = offer.in_stock_lead_time_days or offer.order_lead_time_days or 0


def _reset_visa(calc: Optional[CalcLine]) -> bool:
    if calc is None or calc.visa_at is None:
        return False
    calc.visa_by = None
    calc.visa_by_name = ""
    calc.visa_zone = ""
    calc.visa_item_version = None
    calc.visa_at = None
    return True


def _log(deal: Deal, user, action: str, detail: str, event_code: str, params: dict) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail[:2000],
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=deal.id,
        deal=deal,
        company_id=deal.company_id,
        event_code=event_code,
        event_params=params,
    )


def _recalc(quote: Quote) -> list[int]:
    """Пересчёт КП; возвращает строки, чья сумма после пересчёта по курсу не влезла в поле (их значения не тронуты).

    Итог КП, не влезающий в поле, — понятный отказ 409, а не 500 (прод, ЗВ-2026-002, 2026-11-16: закупка в сумах стояла у
    строки с валютой USD)."""
    from .quotes import QuoteCalculationService

    try:
        result = QuoteCalculationService.recalculate_quote(quote.id)
    except DataError:
        raise CalcError("AMOUNT_TOO_LARGE", 409) from None
    return list(getattr(result, "amount_overflow_ids", []) or [])


def _link_catalog(quote: Optional[Quote]) -> None:
    """Каждая строка расчёта — со своей карточкой каталога: найденной или черновиком (ADR-0027). Строка, похожая на
    карточку каталога, черновика не получает и ждёт решения человека («Похоже: …», СЦ-10)."""
    from catalog.candidates import link_quote_lines

    if quote is None:
        return
    _hint_catalog(quote)
    link_quote_lines(quote, hold_hinted=True)


def _hint_catalog(quote: Quote) -> None:
    """Строкам без карточки и без решения человека — подсказка похожей карточки, если точного совпадения нет."""
    from catalog.candidates import _owner_for, find_existing_card, suggest_card

    items = [
        item
        for item in quote.items.filter(display_type=QuoteItem.DisplayType.ITEM, product__isnull=True).select_related(
            "calc"
        )
        if not (getattr(item, "calc", None) and (item.calc.catalog_hint_id or item.calc.catalog_hint_dismissed))
    ]
    if not items:
        return
    owner = _owner_for(quote)
    for item in items:
        if owner is not None and find_existing_card(item, owner) is not None:
            continue  # точное совпадение привяжет `link_quote_lines`, подсказка не нужна
        card = suggest_card(item, owner)
        if card is not None:
            CalcLine.objects.update_or_create(item=item, defaults={"catalog_hint": card})


@transaction.atomic
def add_lines(deal_id: int, user, rows: list[LineInput]) -> dict:
    """Новые строки в черновик расчёта (вручную или подтверждённое предложение ИИ-разбора). Строка услуги — право
    `quote.visa_services`, товара — `quote.visa_goods`. Расчёт не начат — сначала черновик из заявки."""
    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    if not rows:
        raise CalcError("LINES_REQUIRED", 400)
    if len(rows) > MAX_LINES_PER_CALL:
        raise CalcError("TOO_MANY_LINES", 400)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    if calc_quote(deal) is None:
        start(deal_id, user)
    quote = _draft_or_409(deal)
    prepared = []
    for row in rows:
        product = _product(row.product_id)
        zone = (
            (Zone.SERVICES if product.is_service else Zone.GOODS)
            if product is not None
            else (Zone.SERVICES if row.kind == CalcLineKind.SERVICE else Zone.GOODS)
        )
        _require_zone(user, zone)
        prepared.append((row, product))
    position = (quote.items.aggregate(top=Max("position"))["top"] or 0) + 1
    max_name = QuoteItem._meta.get_field("imported_raw_name").max_length
    from core.units import unit_resolver

    resolve_unit = unit_resolver()
    created = []
    for offset, (row, product) in enumerate(prepared):
        name = (row.name or (product.name if product else "")).strip()
        if not name:
            raise CalcError("NAME_REQUIRED", 400)
        item = QuoteItem(
            quote=quote,
            position=position + offset,
            product=product,
            imported_raw_name=name[:max_name],
            quantity=_quantity(row.quantity),
            unit=(row.unit or "").strip()[:32],
            mpn=(row.article or "").strip()[:120],
            note=(row.note or "").strip(),
        )
        # ADR-0027 п. 10: единица — из справочника; текст узнаётся по справочнику (СЦ-10); без единицы — единица
        # карточки каталога.
        if row.unit_code:
            item.unit_code, item.unit = _unit(row.unit_code)
        elif item.unit:
            item.unit_code, item.unit = resolve_unit(item.unit) or ("", item.unit)
        elif product is not None and product.uom_id:
            item.unit_code, item.unit = product.uom.code, product.uom.name[:32]
        if quote.cost_currency_default_id:
            item.frozen_currency_id = quote.cost_currency_default_id
        _prefill_from_offer(item, product)
        item.save(skip_recalculate=True)
        CalcLine.objects.create(
            item=item, kind=CalcLineKind.SERVICE if row.kind == CalcLineKind.SERVICE else CalcLineKind.GOODS
        )
        created.append(item.id)
    _link_catalog(quote)
    _recalc(quote)
    _log(
        deal,
        user,
        "Строки добавлены в расчёт",
        f"{len(created)} {pluralize_ru(len(created), 'строка', 'строки', 'строк')} в расчёт по {task.label}",
        "calc.lines_added",
        {"count": len(created), "letter_number": task.label},
    )
    return {"created": created, **_sheet(deal, task, user)}


#: План 1.5: сколько прошлых расчётов клиента показать в «Как в прошлой заявке».
MAX_PREVIOUS = 20


def _previous_items(quote: Quote) -> list[QuoteItem]:
    return list(
        quote.items.filter(display_type=QuoteItem.DisplayType.ITEM, is_optional=False)
        .select_related("product", "calc")
        .order_by("position", "id")
    )


def previous_calcs(deal_id: int, user) -> list[dict]:
    """План 1.5: прошлые расчёты того же клиента (новые сверху) — что можно взять за основу этой заявки."""
    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _deal_or_404(deal_id)
    _task_or_404(deal)
    if not deal.company_id:
        return []
    rows = []
    others = (
        Deal.objects.filter(company_id=deal.company_id)
        .exclude(pk=deal.pk)
        .order_by("-created_at", "-id")
        .only("id", "number", "title", "created_at")
    )
    for other in others[: MAX_PREVIOUS * 3]:
        quote = calc_quote(other)
        if quote is None:
            continue
        items = _previous_items(quote)
        if not items:
            continue
        rows.append(
            {
                "deal_id": other.pk,
                "number": other.number or "",
                "title": other.title or "",
                "created_at": other.created_at,
                "lines": len(items),
                "names": [item.imported_raw_name or (item.product.name if item.product else "") for item in items[:3]],
            }
        )
        if len(rows) >= MAX_PREVIOUS:
            break
    return rows


def copy_lines(deal_id: int, user, from_deal_id: int) -> dict:
    """План 1.5: «Как в прошлой заявке» — состав прошлого расчёта того же клиента новыми строками черновика.

    Копируются позиция, карточка каталога, количество, единица, артикул, примечание и тип строки; цены — сегодняшние:
    строки идут тем же путём, что ручные (`add_lines` подставляет действующие цены партнёров). Чужой клиент — 404.
    """
    deal = _deal_or_404(deal_id)
    source_deal = Deal.objects.filter(pk=from_deal_id).first()
    if source_deal is None or source_deal.pk == deal.pk or source_deal.company_id != deal.company_id:
        raise CalcError("DEAL_NOT_FOUND", 404)
    source = calc_quote(source_deal)
    items = _previous_items(source) if source is not None else []
    if not items:
        raise CalcError("NOTHING_TO_COPY", 409)
    # Строки своей зоны (товары — снабженец, услуги — гл. инженер): чужую зону добавит коллега тем же действием.
    mine = [item for item in items if has_perm(user, ZONE_PERMISSION[zone_of(item)])][:MAX_LINES_PER_CALL]
    if not mine:
        raise CalcError("ZONE_NOT_PERMITTED", 403, zone=zone_of(items[0]))
    rows = [
        LineInput(
            name=item.imported_raw_name or (item.product.name if item.product else ""),
            quantity=item.quantity or Decimal("1"),
            unit=item.unit or "",
            unit_code=item.unit_code or "",
            kind=(calc_of(item).kind if calc_of(item) is not None else CalcLineKind.GOODS),
            product_id=item.product_id,
            article=item.mpn or "",
            note=item.note or "",
        )
        for item in mine
    ]
    result = add_lines(deal_id, user, rows)
    result["skipped"] = len(items) - len(mine)
    _log(
        deal,
        user,
        "Состав скопирован из прошлой заявки",
        f"{len(rows)} {pluralize_ru(len(rows), 'строка', 'строки', 'строк')} из {source_deal.number}",
        "calc.lines_copied",
        {"count": len(rows), "from": source_deal.number},
    )
    return result


def _locked_item(quote: Quote, item_id: int) -> QuoteItem:
    item = (
        QuoteItem.objects.select_for_update(of=("self",))
        .select_related("product__domain_type", "frozen_currency")
        .filter(pk=item_id, quote=quote, display_type=QuoteItem.DisplayType.ITEM)
        .first()
    )
    if item is None:
        raise CalcError("LINE_NOT_FOUND", 404)
    return item


_EDITABLE = (
    "name",
    "quantity",
    "unit",
    "unit_code",
    "lead_days",
    "purchase_price",
    "purchase_currency",
    "crew_rate",
    "crew_days",
    "client_price",
    "markup_pct",
    "product_id",
    "kind",
)


@transaction.atomic
def update_line(deal_id: int, item_id: int, user, data: dict) -> dict:
    """Правка строки держателем права её зоны; любая правка снимает визу строки."""
    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    changes = {key: data[key] for key in _EDITABLE if key in data}
    if not changes:
        raise CalcError("NOTHING_TO_CHANGE", 400)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    quote = _draft_or_409(deal)
    item = _locked_item(quote, item_id)
    calc, _ = CalcLine.objects.get_or_create(item=item)
    zone = zone_of(item)
    _require_zone(user, zone)

    replaced_draft = None
    if "product_id" in changes:
        from catalog.candidates import is_own_draft

        # Человек решил по подсказке (СЦ-10): выбрал карточку или «Новая позиция» (`product_id: null`).
        calc.catalog_hint = None
        calc.catalog_hint_dismissed = True
        replaced_draft = item.product_id if item.product_id and is_own_draft(item) else None
        if changes["product_id"] is None and replaced_draft is not None:
            # «Новая позиция» у строки, у которой уже свой черновик, — ничего не меняется (без второго спроса).
            changes.pop("product_id")
    if "product_id" in changes:
        product = _product(changes["product_id"])
        new_zone = (Zone.SERVICES if product.is_service else Zone.GOODS) if product is not None else zone
        _require_zone(user, new_zone)
        if item.offer_id and (product is None or item.offer.product_id != product.id):
            item.offer = None
        if product is None:
            # Снять карточку — строка остаётся в своей зоне: тип строки без карточки берётся из прежней зоны.
            calc.kind = CalcLineKind.SERVICE if zone == Zone.SERVICES else CalcLineKind.GOODS
        item.product = product
        if product is not None:
            _prefill_from_offer(item, product)
        zone = new_zone
    own_draft = False
    if "kind" in changes:
        from catalog.candidates import is_own_draft

        own_draft = bool(item.product_id) and is_own_draft(item)
        if item.product_id and not own_draft:
            raise CalcError("KIND_FROM_CATALOG", 400)
        kind = CalcLineKind.SERVICE if changes["kind"] == CalcLineKind.SERVICE else CalcLineKind.GOODS
        new_zone = Zone.SERVICES if kind == CalcLineKind.SERVICE else Zone.GOODS
        _require_zone(user, new_zone)
        if new_zone != zone:
            # Другой тип — другие вводные закупки: прежняя цена и бригада не переносятся.
            item.frozen_base_price = Decimal("0")
            calc.crew_rate = None
            calc.crew_days = None
        calc.kind = kind
        zone = new_zone
        if own_draft:
            from catalog.candidates import set_draft_kind

            set_draft_kind(item, kind)  # свой черновик меняет тип вместе со строкой
    old_name = item.imported_raw_name
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise CalcError("NAME_REQUIRED", 400)
        item.imported_raw_name = name[: QuoteItem._meta.get_field("imported_raw_name").max_length]
        if not item.product_id:
            calc.catalog_hint = None  # подсказка пересчитается по новому имени
    if "quantity" in changes:
        item.quantity = _quantity(changes["quantity"])
    if "unit" in changes:
        item.unit = (changes["unit"] or "").strip()[:32]
    if "unit_code" in changes:
        item.unit_code, item.unit = _unit(changes["unit_code"])
    if "lead_days" in changes:
        item.lead_time_days = int(changes["lead_days"] or 0)
    if "purchase_price" in changes or "purchase_currency" in changes:
        if zone == Zone.SERVICES:
            raise CalcError("SERVICE_COST_FROM_CREW", 400)
        _require(user, Permission.QUOTE_EDIT_PRICING.value)
        if "purchase_price" in changes:
            item.frozen_base_price = Decimal(str(changes["purchase_price"]))
        if changes.get("purchase_currency"):
            item.frozen_currency = _currency(changes["purchase_currency"])
    if "crew_rate" in changes or "crew_days" in changes:
        if zone != Zone.SERVICES:
            raise CalcError("GOODS_HAVE_NO_CREW", 400)
        if "crew_rate" in changes:
            calc.crew_rate = None if changes["crew_rate"] is None else Decimal(str(changes["crew_rate"]))
        if "crew_days" in changes:
            calc.crew_days = None if changes["crew_days"] is None else Decimal(str(changes["crew_days"]))
        if calc.crew_rate is not None and calc.crew_days is not None:
            item.frozen_base_price = (calc.crew_rate * calc.crew_days).quantize(_CENT, rounding=ROUND_HALF_UP)
        else:
            item.frozen_base_price = Decimal("0")
        item.frozen_currency = _currency(BASE_CURRENCY) if _has_currency(BASE_CURRENCY) else None
    # Зона строки ПОСЛЕ правки (карточка или тип строки): правит тот, у кого право и прежней, и новой зоны.
    final_zone = (
        (Zone.SERVICES if item.product.is_service else Zone.GOODS)
        if item.product_id
        else (Zone.SERVICES if calc.kind == CalcLineKind.SERVICE else Zone.GOODS)
    )
    _require_zone(user, final_zone)
    _reset_visa(calc)
    calc.save()
    item.version = (item.version or 0) + 1
    item.save()  # пересчёт КП с курсами строк — в QuoteItem.save
    if "name" in changes:
        from catalog.candidates import relink_renamed_line

        relink_renamed_line(item, old_name)
    _link_catalog(quote)
    item.refresh_from_db(fields=["product"])
    if replaced_draft and replaced_draft != item.product_id:
        from catalog.candidates import drop_unused_draft

        drop_unused_draft(replaced_draft)  # строку сопоставили с каталогом — свой черновик больше не нужен
    if "product_id" in changes or "quantity" in changes:
        from inventory.services import stock

        stock.sync_reservation(item)  # другой товар или меньшее количество — резерв подгоняется (D2-2)
    _apply_price(item, calc, changes, user)
    _log(
        deal,
        user,
        "Строка расчёта изменена",
        f"«{item.imported_raw_name}»: {', '.join(sorted(changes))}",
        "calc.line_updated",
        {"item_id": item.id, "fields": sorted(changes)},
    )
    return _sheet(deal, task, user)


def _has_currency(code: str) -> bool:
    from master_data.models import Currency

    return Currency.objects.filter(code=code).exists()


def _apply_price(item: QuoteItem, calc: CalcLine, changes: dict, user) -> None:
    """Цена клиенту строки после правки (D26G-5). Введённая цена — источник истины: хранится как есть
    (`client_price_fixed`), наценка — производная. Введённая наценка — цена считается из неё и округляется до сума
    (в валюте КП не UZS — до 0,01) и тоже хранится. Правка закупки без цены: у строки «от наценки» цена
    пересчитывается от той же наценки, у строки «от цены» цена остаётся, а наценка пересчитывается."""
    pricing = "client_price" in changes or "markup_pct" in changes
    if not pricing and item.client_price_fixed is None:
        return
    if pricing:
        _require(user, Permission.QUOTE_EDIT_PRICING.value)
    item.refresh_from_db()
    if "markup_pct" in changes:
        markup = Decimal(str(changes["markup_pct"])).quantize(_CENT, rounding=ROUND_HALF_UP)
        item.client_price_fixed = _price_for(item, markup)
        item.margin_percent = markup
        calc.price_basis = CalcPriceBasis.MARKUP
    elif "client_price" in changes:
        price = Decimal(str(changes["client_price"])).quantize(_CENT, rounding=ROUND_HALF_UP)
        item.margin_percent = _markup_for(item, price)
        item.client_price_fixed = price
        calc.price_basis = CalcPriceBasis.CLIENT
    elif calc.price_basis == CalcPriceBasis.MARKUP and item.margin_percent is not None:
        try:
            item.client_price_fixed = _price_for(item, item.margin_percent)
        except CalcError:
            pass  # закупку сняли — прежняя цена остаётся до новой закупки
    else:
        try:
            item.margin_percent = _markup_for(item, item.client_price_fixed)
        except CalcError:
            pass  # закупка выше цены или пуста — наценка справочная, цена клиенту не меняется
    calc.save(update_fields=["price_basis", "updated_at"])
    item.save()


def _price_quantum(item: QuoteItem) -> Decimal:
    currency = item.quote.quote_currency if item.quote.quote_currency_id else None
    code = (getattr(currency, "code", "") or BASE_CURRENCY).upper()
    return Decimal("1") if code == BASE_CURRENCY else _CENT


def _price_for(item: QuoteItem, markup: Decimal) -> Decimal:
    """Цена клиенту без НДС за единицу из наценки строки (с учётом скидки), округлённая до сума."""
    if markup < 0 or markup > _MARKUP_MAX:
        raise CalcError("MARKUP_OUT_OF_RANGE", 400)
    cost = item.landed_cost or Decimal("0")
    if cost <= 0:
        raise CalcError("PURCHASE_REQUIRED", 409)
    discount = Decimal("1") - (item.discount_percent or Decimal("0")) / Decimal("100")
    price = cost * (Decimal("1") + markup / Decimal("100")) * discount
    return price.quantize(_price_quantum(item), rounding=ROUND_HALF_UP)


def _markup_for(item: QuoteItem, client_price: Decimal) -> Decimal:
    """Наценка строки, при которой цена клиенту без НДС равна заданной (с учётом скидки строки)."""
    cost = item.landed_cost or Decimal("0")
    if cost <= 0:
        raise CalcError("PURCHASE_REQUIRED", 409)
    discount = Decimal("1") - (item.discount_percent or Decimal("0")) / Decimal("100")
    if discount <= 0:
        raise CalcError("MARKUP_OUT_OF_RANGE", 400)
    markup = ((client_price / (cost * discount)) - Decimal("1")) * Decimal("100")
    markup = markup.quantize(_CENT, rounding=ROUND_HALF_UP)
    if markup < 0:
        raise CalcError("CLIENT_PRICE_BELOW_COST", 400)
    if markup > _MARKUP_MAX:
        raise CalcError("MARKUP_OUT_OF_RANGE", 400)
    return markup


@transaction.atomic
def delete_line(deal_id: int, item_id: int, user) -> dict:
    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    quote = _draft_or_409(deal)
    item = _locked_item(quote, item_id)
    _require_zone(user, zone_of(item))
    name = item.imported_raw_name
    from inventory.services import stock

    stock.release_for_item(item)  # резерв удаляемой строки снимается (D2-2)
    item.delete()
    _recalc(quote)
    _log(deal, user, "Строка удалена из расчёта", f"«{name}»", "calc.line_deleted", {"item_id": item_id})
    return _sheet(deal, task, user)


# ── условия КП ─────────────────────────────────────────────────────────────────────────────────────────────────────

#: Поле запроса → поле КП. Пустая строка и null очищают значение: срок поставки — снова максимум по строкам.
_TERMS = {
    "payment_terms": "payment_terms",
    "valid_until": "valid_until",
    "delivery_days": "delivery_lead_time_days",
    "delivery_note": "delivery_note",
}


@transaction.atomic
def update_terms(deal_id: int, user, data: dict) -> dict:
    """Условия КП (FR-16): оплата, срок действия и срок поставки задаются в черновике; визы строк не снимаются."""
    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    changes = {_TERMS[key]: value for key, value in data.items() if key in _TERMS}
    if not changes:
        raise CalcError("NOTHING_TO_CHANGE", 400)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    quote = _draft_or_409(deal)
    if changes.get("valid_until") is not None and changes["valid_until"] < timezone.localdate():
        raise CalcError("VALID_UNTIL_IN_PAST", 400)
    for field_name in ("payment_terms", "delivery_note"):
        if field_name in changes:
            changes[field_name] = (changes[field_name] or "").strip()
    changed = [name for name, value in changes.items() if getattr(quote, name) != value]
    if changed:
        for name in changed:
            setattr(quote, name, changes[name])
        quote.save(update_fields=[*changed, "updated_at"])
        _log(deal, user, "Условия КП изменены", ", ".join(changed), "calc.terms_updated", {"fields": changed})
    return _sheet(deal, task, user)


# ── виза строки ────────────────────────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def sign_line(deal_id: int, item_id: int, user) -> dict:
    """«Подтвердить» строку: держатель права зоны строки; у строки есть закупка и цена клиенту. Повтор — без изменений."""
    _require_staff(user)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    quote = _draft_or_409(deal)
    item = _locked_item(quote, item_id)
    zone = zone_of(item)
    _require_zone(user, zone)
    calc, _ = CalcLine.objects.get_or_create(item=item)
    if is_signed(item, calc):
        return _sheet(deal, task, user)
    if calc.catalog_hint_id and not item.product_id:
        raise CalcError("CATALOG_MATCH_PENDING", 409)  # СЦ-10: сначала «Выбрать» или «Новая позиция»
    if (item.landed_cost or 0) <= 0 or (item.final_price_excl_vat or 0) <= 0:
        raise CalcError("LINE_INCOMPLETE", 409)
    calc.visa_by = user
    calc.visa_by_name = person_name(user)[:255]
    calc.visa_zone = zone
    calc.visa_item_version = item.version
    calc.visa_at = timezone.now()
    calc.save()
    _log(
        deal,
        user,
        "Строка расчёта подтверждена",
        f"«{item.imported_raw_name}» ({'услуги' if zone == Zone.SERVICES else 'товары'})",
        "calc.line_signed",
        {"item_id": item.id, "zone": zone},
    )
    items = _billable(quote)
    if items and all(_signed(it) for it in items):
        _notify_all_signed(deal, task, user)
    return _sheet(deal, task, user)


def _signed(item: QuoteItem) -> bool:
    return is_signed(item)


def _notify_all_signed(deal: Deal, task: CalcTask, actor) -> None:
    """SPEC-v3 §9 «все визы собраны»: исполнителям задания (кроме подписавшего последним) — колокольчик ERP."""
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    from .calc_tasks import visa_assignees

    ntype = NotificationType.objects.filter(code="INFO").first()
    seen: set[int] = set()
    for _crm_id, _zone, user_id in visa_assignees(task, persist=False):
        if not user_id or user_id == actor.pk or user_id in seen:
            continue
        seen.add(user_id)
        notification = Notification.objects.create(
            user_id=user_id,
            type=ntype,
            title="Все строки расчёта подтверждены",
            message=f"Расчёт по {task.label}: все визы собраны, можно нажать «Расчёт готов».",
            link=f"#deal/{deal.id}",
            deal=deal,
            event_code="calc.all_signed",
            event_params={"deal_id": deal.id, "letter_number": task.label},
        )
        push_notification_ws(notification)


# ── «Расчёт готов → черновик КП директору» ─────────────────────────────────────────────────────────────────────────


@transaction.atomic
def mark_ready(deal_id: int, user) -> dict:
    """Все строки завизированы → КП на одобрение директору в EDS (`quote.ready_for_approval`), КП «На утверждении».

    Проверки — как у отправки КП на согласование (`submit_for_review`): клиент заявки, ненулевая сумма, курсы строк,
    не в убыток. Визы строк заменяют визы КП: цепочка шагов ERP не строится."""
    from sales.services.quote_fx import fix_quote_rates

    from .eds_quote_approval import request_director_approval
    from .quotes._shared import _set_quote_status
    from .quotes.lifecycle_gates import assert_submittable, resolve_submit_company
    from .quotes.pricing import compute_quote_economics

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _locked_deal_or_404(deal_id)
    task = _task_or_404(deal)
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    if stage not in OPEN_STAGES:
        # Заявка закрыта, проиграна или ушла дальше расчёта — КП директору из расчёта не отправляется.
        raise CalcError("DEAL_NOT_IN_CALCULATION", 409, stage=stage)
    quote = _draft_or_409(deal)
    items = _billable(quote)
    if not items:
        raise CalcError("NO_LINES", 409)
    missing = [it.id for it in items if not _signed(it)]
    if missing:
        raise CalcError("VISAS_MISSING", 409, missing=len(missing))
    apply_delivery_leads(quote, items)  # срок КП и договора — с учётом поставщика на дефицит (D26G-8)
    company_id, err = resolve_submit_company(quote, user)
    if err:
        raise CalcError(err, 403 if err == "ROLE_NOT_PERMITTED" else 409)
    # Пересчёт перед отправкой всегда: строка, чья сумма по сегодняшнему курсу не влезает в поле (обычно сумма в сумах у
    # строки в USD), — отказ с числом таких строк, а не КП с неверной ценой и не 500.
    _link_catalog(quote)
    overflow = _recalc(quote)
    quote.refresh_from_db()
    if overflow:
        raise CalcError("AMOUNT_TOO_LARGE", 409, lines=len(overflow))
    err = assert_submittable(quote, compute_quote_economics(quote))
    if err:
        raise CalcError(err, 409)
    if not deal.company_id:
        raise CalcError("QUOTE_CLIENT_REQUIRED", 409)
    claim = []
    if not quote.prepared_by_id:
        quote.prepared_by = user
        claim.append("prepared_by")
    if not quote.seller_company_id:
        quote.seller_company_id = company_id
        claim.append("seller_company")
    if claim:
        quote.save(update_fields=[*claim, "updated_at"])
    _set_quote_status(quote, QuoteStatusCode.PENDING_APPROVAL)
    fix_quote_rates(quote, user)
    request_director_approval(quote, user, line_visas=True)
    _log(
        deal,
        user,
        "Расчёт готов: черновик КП у директора",
        f"{quote.number or 'КП'} по {task.label}: все визы собраны",
        "calc.ready",
        {"letter_number": task.label, "number": quote.number, "lines": len(items)},
    )
    return _sheet(deal, task, user)


# ── «Клиент отклонил КП»: новая версия или отказ по заявке (D26G-3, SPEC-v3 §3.3) ──────────────────────────────────


def _rejected_or_409(deal: Deal, user) -> Quote:
    quote = calc_quote(deal)
    if quote is None:
        raise CalcError("CALC_NOT_STARTED", 409)
    if not _can_revise(deal, quote, user):
        raise CalcError("QUOTE_NOT_REJECTED_BY_CLIENT", 409)
    return quote


@transaction.atomic
def new_version(deal_id: int, user) -> dict:
    """«Новая версия КП»: клиент отклонил КП — расчёт снова открыт черновиком версии +1 с теми же строками и тем же
    номером КП (новая строка КП: прежняя версия остаётся в истории отклонённой клиентом).

    Копия — `duplicate_quote` (позиции, статьи, введённые цены); строкам расчёта переносятся тип и вводные бригады,
    визы — нет (новая версия собирает визы заново). Резервы заявки сняты ещё при отказе клиента
    (`perform_quote_rejection` → `inventory.services.stock.release_for_deal`, D26G-1): новая версия резервирует заново.
    """
    from .quotes._shared import _log_quote
    from .quotes.duplicate import duplicate_quote

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _locked_deal_or_404(deal_id)
    task = _task_or_404(deal)
    source = _rejected_or_409(deal, user)
    copy = duplicate_quote(source.pk, user)
    # Версии одного КП несут один номер (SPEC-v3 §2.1–2.2): «КП-2026/NNN, версия 2»; уникальна пара номер + версия.
    copy.number = source.number
    copy.save(update_fields=["number", "updated_at"])
    old_items = list(source.items.order_by("position", "id").select_related("calc"))
    new_items = list(copy.items.order_by("position", "id"))
    for old, new in zip(old_items, new_items, strict=False):
        line = calc_of(old)
        if line is not None:
            CalcLine.objects.create(
                item=new,
                kind=line.kind,
                crew_rate=line.crew_rate,
                crew_days=line.crew_days,
                price_basis=line.price_basis,
            )
    _log_quote(
        source,
        user,
        "КП заменено новой версией",
        f"КП {source.number or '—'}: версия {source.version} отклонена клиентом → черновик версии {copy.version}",
        event_code="quote.superseded",
        event_params={"version": source.version, "number": source.number, "new_version": copy.version},
    )
    _log(
        deal,
        user,
        "Новая версия КП после отказа клиента",
        f"КП v{copy.version} по {task.label}: расчёт снова открыт",
        "calc.new_version",
        {"letter_number": task.label, "version": copy.version, "previous_version": source.version},
    )
    return _sheet(deal, task, user)


@transaction.atomic
def lose(deal_id: int, user, reason: str) -> dict:
    """«Отказ по заявке» после отказа клиента: стадия «Отказ» (CLOSED_LOST) с причиной, событие `deal.lost`;
    резервы заявки снимает переход стадии (`inventory.services.stock.release_for_lost_deal` → `release_for_deal`, D26G-1;
    после отказа клиента их уже нет — снятие идемпотентно)."""
    from .deals import transition_deal_stage

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    reason = (reason or "").strip()
    if not reason:
        raise CalcError("REASON_REQUIRED", 400)
    deal = _locked_deal_or_404(deal_id)
    task = _task_or_404(deal)
    quote = _rejected_or_409(deal, user)
    _deal, err = transition_deal_stage(
        deal,
        DealStageCode.CLOSED_LOST,
        actor=user,
        reason=f"Отказ по заявке после отказа клиента от КП v{quote.version}: {reason}",
        lost_reason=reason,
    )
    if err:
        raise CalcError(err, 409)
    _log(
        deal,
        user,
        "Отказ по заявке",
        f"{task.label}: {reason}",
        "calc.lost",
        {"letter_number": task.label, "reason": reason, "version": quote.version},
    )
    deal.refresh_from_db()
    return _sheet(deal, task, user)


# ── «Закрыть заявку» на любом шаге до проекта (ЛХ-2) ──────────────────────────────────────────────────────────────

#: Стадии, из которых заявку можно закрыть: всё до принятия КП (договор и дальше — проект, не заявка).
CLOSABLE_STAGES = (
    DealStageCode.DRAFT,
    DealStageCode.KYC_PENDING,
    DealStageCode.RFQ_OPEN,
    DealStageCode.SOURCING,
    DealStageCode.CALCULATING,
    DealStageCode.QUOTE_SENT,
)


#: КП, не получившие решения: на проверке, у директора, готово к отправке и отправленное клиенту.
UNFINISHED_QUOTE_STATUSES = (
    QuoteStatusCode.PENDING_TRADE_REVIEW,
    QuoteStatusCode.PENDING_APPROVAL,
    QuoteStatusCode.READY_TO_SEND,
    QuoteStatusCode.SENT,
)


def quote_sent_to_client(deal: Deal) -> bool:
    """КП уже было у клиента: заявка в стадии «КП отправлено», либо КП отправлено, принято или отклонено клиентом.
    Отказ директора КП клиенту не отправляет."""
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    if stage == DealStageCode.QUOTE_SENT:
        return True
    for quote in Quote.objects.filter(deal=deal).select_related("status"):
        code = quote.status.code if quote.status_id else QuoteStatusCode.DRAFT
        if code in (QuoteStatusCode.SENT, QuoteStatusCode.APPROVED):
            return True
        if code == QuoteStatusCode.REJECTED and quote.director_decision != "reject":
            return True
    return False


def _is_request_owner(deal: Deal, user) -> bool:
    """Ответственный заявки — менеджер или взявший в работу. Исполнитель резолюции (визы расчёта) владельцем не считается."""
    return user.pk in (deal.manager_id, deal.assigned_to_id)


def can_close_request(deal: Deal, user) -> bool:
    """Закрыть заявку может её ответственный и держатель зоны продаж (`deal.manage`); администратор — всегда."""
    if not (getattr(user, "is_superuser", False) or is_seller(user)):
        return False
    return has_perm(user, Permission.DEAL_MANAGE.value) or _is_request_owner(deal, user)


def close_state(deal: Deal, user) -> dict:
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    reason = deal.close_reason if deal.close_reason_id else None
    return {
        "allowed": stage in CLOSABLE_STAGES and not deal.is_project and can_close_request(deal, user),
        "quote_sent": quote_sent_to_client(deal) if stage in CLOSABLE_STAGES else deal.closed_after_quote_sent,
        "reason": reason.code if reason else None,
        "comment": deal.close_comment or None,
    }


def _request_card(deal: Deal, task: Optional[CalcTask], user) -> dict:
    """Карточка заявки для «Закрыть заявку»: заявка, её текст и файлы, что можно и чем закрыта — с заданием расчёта и без."""
    from .draft_quote import deal_request_files, deal_request_lines_count, deal_request_text

    return {
        "deal": _deal_brief(deal),
        "has_task": task is not None,
        "request": {
            "text": deal_request_text(deal),
            "lines": deal_request_lines_count(deal),
            "files": deal_request_files(deal),
            "files_pending": bool(task.request_file_pending) if task is not None else False,
            "crm_client_id": _crm_client_id(deal),
        },
        "close": close_state(deal, user),
    }


def request_card(deal_id: int, user) -> dict:
    _require_staff(user)
    deal = _deal_or_404(deal_id)
    return _request_card(deal, latest_task(deal.id), user)


def close_reasons(user) -> list[dict]:
    """Действующие причины закрытия (справочник `request-close-reasons`) с правилами — для диалога."""
    from ..models import DealCloseReason

    _require_staff(user)
    return [
        {
            "code": row.code,
            "name": {"ru": row.name, "uz": row.name_uz, "en": row.name_en},
            "requires_comment": row.requires_comment,
            "allowed_after_quote_sent": row.allowed_after_quote_sent,
            "preselect_after_client_rejection": row.preselect_after_client_rejection,
        }
        for row in DealCloseReason.objects.filter(is_active=True).order_by("sort_order", "name")
    ]


@transaction.atomic
def close_request(deal_id: int, user, reason_code: str, comment: str = "") -> dict:
    """«Закрыть заявку» на любом шаге до проекта: стадия «Отказ» (CLOSED_LOST) с причиной из справочника, событие
    `deal.lost` в CRM, резервы снимает переход стадии. КП уже у клиента — только причины с `allowed_after_quote_sent`;
    отправленное КП закрывается (клиент не примет его после закрытия). «Ошибка» и «Тест» без отправленных клиенту
    документов скрывают заявку из списков (`hidden_in_lists`); запись и журнал остаются — удаления нет."""
    from ..models import DealCloseReason

    _require_staff(user)
    deal = _locked_deal_or_404(deal_id)
    task = latest_task(deal.id)  # заявка без задания расчёта (черновик из передачи) закрывается так же
    if not can_close_request(deal, user):
        raise CalcError("ROLE_NOT_PERMITTED", 403)
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    if stage not in CLOSABLE_STAGES or deal.is_project:
        raise CalcError("REQUEST_NOT_CLOSABLE", 409)
    reason = DealCloseReason.objects.filter(code=(reason_code or "").strip(), is_active=True).first()
    if reason is None:
        raise CalcError("REASON_UNKNOWN", 400)
    comment = (comment or "").strip()
    if reason.requires_comment and not comment:
        raise CalcError("COMMENT_REQUIRED", 400)
    sent = quote_sent_to_client(deal)
    if sent and not reason.allowed_after_quote_sent:
        raise CalcError("REASON_NOT_ALLOWED_AFTER_QUOTE", 409)
    _close_checked(deal, user, reason, comment, stage, sent, task)
    deal.refresh_from_db()
    return _request_card(deal, task, user)


def close_deal_as(deal: Deal, user, reason, comment: str = "") -> None:
    """Закрыть заявку причиной из справочника без проверки прав (для служебных действий: «Не клиент», КОНТР-1б).

    Вызывающий отвечает за право и за то, что заявка закрываема (`CLOSABLE_STAGES`, не проект); `user=None` — оболочка.
    """
    task = latest_task(deal.id)
    stage = deal.stage.code if deal.stage_id else DealStageCode.DRAFT
    _close_checked(deal, user, reason, (comment or "").strip(), stage, quote_sent_to_client(deal), task)


def _close_checked(deal: Deal, user, reason, comment: str, stage: str, sent: bool, task) -> None:
    from .deals import transition_deal_stage
    from .quotes._shared import _set_quote_status

    lost_reason = f"{reason.name}: {comment}" if comment else reason.name
    _deal, err = transition_deal_stage(
        deal,
        DealStageCode.CLOSED_LOST,
        actor=user,
        reason=f"Заявка закрыта: {lost_reason}",
        lost_reason=lost_reason,
    )
    if err:
        raise CalcError(err, 409)
    # Незавершённые КП закрываются вместе с заявкой (клиент не примет отправленное, директору нечего одобрять): у закрытой
    # заявки нет КП «у директора» и «готово к отправке». Для клиента такое КП — «закрыто», а не «отклонено».
    for quote in Quote.objects.filter(deal=deal, status__code__in=UNFINISHED_QUOTE_STATUSES):
        _set_quote_status(quote, QuoteStatusCode.CLOSED)
    deal.close_reason = reason
    deal.close_comment = comment[:2000]
    deal.closed_from_stage = stage
    deal.closed_after_quote_sent = sent
    deal.hidden_in_lists = bool(reason.hide_when_unsent and not sent)
    deal.save(
        update_fields=[
            "close_reason",
            "close_comment",
            "closed_from_stage",
            "closed_after_quote_sent",
            "hidden_in_lists",
        ]
    )
    _log(
        deal,
        user,
        "Заявка закрыта",
        f"{task.letter_number if task else deal.number}: {lost_reason}",
        "calc.closed",
        {
            "letter_number": task.letter_number if task else None,
            "reason_code": reason.code,
            "reason": reason.name,
            "comment": comment,
        },
    )


def line_visas(quote: Quote) -> list[tuple[str, Any, Any]]:
    """Визы строк КП для события `quote.ready_for_approval`: (зона, пользователь, время) — последняя виза человека в
    зоне. Пусто — КП собиралось без расчёта по строкам (визы — шагами КП)."""
    rows: dict[tuple[str, int], tuple[str, Any, Any]] = {}
    for item in quote.items.billable().select_related("calc__visa_by", "product__domain_type"):
        calc = calc_of(item)
        if calc is None or calc.visa_by_id is None or not is_signed(item, calc):
            continue
        key = (calc.visa_zone, calc.visa_by_id)
        current = rows.get(key)
        if current is None or current[2] < calc.visa_at:
            rows[key] = (calc.visa_zone, calc.visa_by, calc.visa_at)
    return sorted(rows.values(), key=lambda row: (row[0], row[2]))


def line_zones(quote: Quote) -> list[str]:
    return sorted({zone_of(item) for item in quote.items.billable().select_related("product__domain_type", "calc")})


# ── каталог и ИИ-разбор ────────────────────────────────────────────────────────────────────────────────────────────


def catalog_search(user, q: str, *, limit: int = 20) -> list[dict]:
    """Сопоставление строки с каталогом: карточки, у которых в названии, артикуле, коде производителя или ГОСТ есть
    каждое слово запроса. Ничего не нашлось — название с опечатками и в другой письменности (FR-26, `catalog.fuzzy`).
    Детерминированно, без ИИ; человек выбирает карточку сам."""
    from catalog.fuzzy import fuzzy_products
    from catalog.models import Product

    _require_staff(user)
    words = [w for w in (q or "").split() if w][:6]
    if not words:
        return []
    base = Product.objects.select_related("domain_type").exclude(status__code="ARCHIVED")
    qs = base
    for word in words:
        qs = qs.filter(
            Q(name__icontains=word)
            | Q(sku__icontains=word)
            | Q(previous_sku__icontains=word)
            | Q(manufacturer_part_number__icontains=word)
            | Q(gost_drawing__icontains=word)
        )
    products = list(qs.order_by("name")[:limit]) or fuzzy_products(base, " ".join(words), limit=limit)
    from inventory.services import stock as warehouse

    own = _own_offers([p.id for p in products])
    suppliers = _supplier_offers([p.id for p in products])
    states = warehouse.availability(p.id for p in products)
    rows = []
    for product in products:
        offer = suppliers.get(product.id)
        stock = own.get(product.id)
        state = states.get(product.id)
        rows.append(
            {
                "id": product.id,
                "name": product.name,
                "article": product.manufacturer_part_number or product.sku,
                "kind": "service" if product.is_service else "goods",
                "on_hand": (
                    state.free
                    if state is not None and state.tracked
                    else (stock.stock_quantity if stock is not None else 0)
                ),
                "supplier_name": offer.supplier.name if offer is not None else None,
                "lead_days": (offer.order_lead_time_days or offer.in_stock_lead_time_days or None) if offer else None,
            }
        )
    return rows


#: План 1.1: какие файлы заявки разбирает модель (Word — через docling-serve, остальное — `ai.services.payloads`).
PARSE_FILE_TYPES = frozenset({"docx", "xlsx", "xls", "pdf", "png", "jpg", "jpeg", "webp", "csv", "txt", "tsv"})


def parse_payload(deal_id: int, user, text: Optional[str], *, has_file: bool = False) -> dict:
    """Проверки перед ИИ-разбором (дешёвые, до очереди): заявка с заданием, право строить КП, есть текст или файл."""
    from .draft_quote import deal_request_text

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _deal_or_404(deal_id)
    _task_or_404(deal)
    if has_file:
        return {"deal_id": deal.id, "user_id": user.pk, "text": ""}
    source = (text or "").strip() or deal_request_text(deal)
    if not source:
        raise CalcError("REQUEST_TEXT_EMPTY", 409)
    return {"deal_id": deal.id, "user_id": user.pk, "text": source[:20000]}


def parse_file_check(filename: str, content: bytes) -> str:
    """Тип и размер файла заявки до очереди (план 1.1): расширение из списка, подпись файла совпадает с ним."""
    from django.conf import settings

    from core.validators import content_matches_extension

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in PARSE_FILE_TYPES or not content_matches_extension(content[:16], extension):
        raise CalcError("FILE_TYPE_UNSUPPORTED", 400)
    if len(content) > getattr(settings, "AI_IMPORT_MAX_BYTES", 10 * 1024 * 1024):
        raise CalcError("FILE_TOO_LARGE", 400)
    return extension


def parse_proposal(text: str, *, content: Optional[bytes] = None, filename: str = "request.txt") -> dict:
    """ИИ-разбор текста или файла заявки (план 1.1) в строки — ПРЕДЛОЖЕНИЕ: ничего не записывается, строки добавляет
    человек (`add_lines`). Модель — через шлюз ИИ по алиасу (`ai.services.intake`)."""
    from ai.services.intake import extract_request_items

    try:
        if content is not None:
            rows = extract_request_items(content, filename)
        else:
            rows = extract_request_items(text.encode("utf-8"), "request.txt")
    except (RuntimeError, ValueError) as exc:
        logger.warning("AI calc parse failed: %s", exc)
        reason = str(exc)
        if reason.startswith("AI_IMPORT_DISABLED"):
            return {"error": "AI_DISABLED"}
        if reason.startswith("AI_IMPORT_WORD_UNAVAILABLE"):
            return {"error": "WORD_UNAVAILABLE"}
        return {"error": "AI_EXTRACT_FAILED"}
    from core.units import unit_resolver

    resolve_unit = unit_resolver()
    proposal = []
    for row in rows[:MAX_LINES_PER_CALL]:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            quantity = as_qty(_quantity(row.get("quantity") or 1))
        except (ArithmeticError, ValueError):
            quantity = 1
        proposal.append(
            {
                "name": name[:500],
                "quantity": quantity,
                "unit": str(row.get("unit") or "")[:32],
                # СЦ-10: код справочника — из разбора (уже сверен) или узнанный по написанной единице; пусто — не узнан.
                "unit_code": str(row.get("unit_code") or "") or (resolve_unit(row.get("unit")) or ("", ""))[0],
                "article": str(row.get("mpn") or row.get("gost_drawing") or "")[:120],
                "note": str(row.get("note") or "")[:1000],
            }
        )
    return {"proposal": proposal, "recognized": len(rows), "truncated": len(rows) > MAX_LINES_PER_CALL}
