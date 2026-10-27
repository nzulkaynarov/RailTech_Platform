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
* Себестоимость, закупка и наценка по строкам — только держателю `quote.view_cost_margin`; итоги закупки и наценки
  отдаются всем, кто видит расчёт (бухгалтеру — «только итоги», `totals_only`); лишнее вырезает BFF по каталогу.

Ошибки — `CalcError(code, status)`; вьюхи отдают `{"detail": code}`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.constants import Permission
from accounts.services.permissions import is_seller, member_has_permission

from ..constants import DealStageCode, QuoteStatusCode
from ..models import ActivityLog, CalcLine, CalcLineKind, CalcTask
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


def _context(items: list[QuoteItem]) -> _Context:
    ids = [it.product_id for it in items if it.product_id]
    return _Context(own=_own_offers(ids), suppliers=_supplier_offers(ids))


def _line_kind(item: QuoteItem, zone: str, ctx: _Context) -> tuple[str, Optional[int]]:
    """Тип для экрана: услуга; товар со склада (остаток покрывает количество); товар под заказ."""
    if zone == Zone.SERVICES:
        return "service", None
    own = ctx.own.get(item.product_id) if item.product_id else None
    on_hand = own.stock_quantity if own is not None else (0 if item.product_id else None)
    if on_hand is not None and on_hand >= item.quantity and on_hand > 0:
        return "goods", on_hand
    return "goods_to_order", on_hand


def _visa_group(kind: str) -> str:
    return {"goods": "stock", "goods_to_order": "supply", "service": "engineer"}[kind]


def line_payload(item: QuoteItem, ctx: _Context, *, show_cost: bool, rights: dict[str, bool], editable: bool) -> dict:
    zone = zone_of(item)
    kind, on_hand = _line_kind(item, zone, ctx)
    calc = calc_of(item)
    signed = calc is not None and calc.visa_at is not None and calc.visa_zone == zone
    supplier = None
    offer = item.offer if item.offer_id and item.offer.supplier_id != _own_company_id() else None
    offer = offer or (ctx.suppliers.get(item.product_id) if item.product_id and zone == Zone.GOODS else None)
    if offer is not None:
        supplier = {
            "name": offer.supplier.name,
            "lead_days": offer.order_lead_time_days or offer.in_stock_lead_time_days or None,
            "min_order_qty": offer.min_order_qty,
            "price_valid_until": offer.valid_until.isoformat() if offer.valid_until else None,
            "offer_price": _money(offer.base_price),
            "offer_currency": offer.currency.code if offer.currency_id else None,
        }
    cost = item.landed_cost if show_cost else None
    product = item.product if item.product_id else None
    return {
        "id": item.id,
        "position": item.position,
        "name": item.imported_raw_name or (product.name if product else "") or f"Позиция #{item.id}",
        "article": item.mpn
        or (product.manufacturer_part_number if product else "")
        or (product.sku if product else ""),
        "product_id": item.product_id,
        "product_name": product.name if product else None,
        "kind": kind,
        "zone": zone,
        "quantity": item.quantity,
        "unit": item.unit,
        "stock": {"on_hand": on_hand, "cell": None, "reserved": None},
        "supplier": supplier,
        "lead_days": item.lead_time_days or None,
        "purchase_price": _money(item.frozen_base_price) if show_cost and zone == Zone.GOODS else None,
        "purchase_currency": (
            (item.frozen_currency.code if item.frozen_currency_id else "UZS") if zone == Zone.GOODS else "UZS"
        ),
        "crew_rate": _money(calc.crew_rate) if calc is not None and calc.crew_rate is not None else None,
        "crew_days": str(calc.crew_days) if calc is not None and calc.crew_days is not None else None,
        "cost": _money(cost) if show_cost else None,
        "client_price": _money(item.final_price_excl_vat),
        "markup_pct": _markup(item.landed_cost, item.final_price_excl_vat) if show_cost else None,
        "visa": (
            {
                "by": calc.visa_by_name or person_name(calc.visa_by),
                "at": calc.visa_at.isoformat(),
            }
            if signed
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


def _billable(quote: Optional[Quote]) -> list[QuoteItem]:
    if quote is None:
        return []
    return list(
        quote.items.billable()
        .select_related("product__domain_type", "frozen_currency", "offer__supplier", "offer__currency", "calc")
        .select_related("calc__visa_by")
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
        if calc is not None and calc.visa_at is not None and calc.visa_zone == zone:
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
        "title": deal.title,
        "created_at": deal.created_at.isoformat(),
        "stage_code": deal.stage.code if deal.stage_id else DealStageCode.DRAFT,
        "client_name": deal.company.name if deal.company_id else None,
        "manager_name": person_name(deal.manager) if deal.manager_id else None,
    }


def _task_brief(task: CalcTask) -> dict:
    return {
        "letter_number": task.letter_number,
        "letter_subject": task.letter_subject,
        "resolution_text": task.resolution_text,
        "decided_at": task.decided_at.isoformat(),
        "decided_by_name": task.decided_by_name or None,
        "due": task.due.isoformat(),
        "min_margin_pct": None if task.min_margin_pct is None else f"{task.min_margin_pct:.2f}",
    }


# ── список «Заявки в расчёте» ──────────────────────────────────────────────────────────────────────────────────────


def _mapped_crm_ids(user) -> set[int]:
    from integration.models import CrmUserMapping

    return set(CrmUserMapping.objects.filter(user=user).values_list("crm_user_id", flat=True))


def list_tasks(user, *, mine: bool = False, scope: str = "open") -> list[dict]:
    """Заявки с заданием расчёта: последняя резолюция каждой, срок, индикаторы виз, ответственный.

    `scope=open` — заявки на стадиях «Расчёт» (подбор, расчёт); `all` — все с заданием (адресация карточки по
    номеру). `mine` — где сотрудник исполнитель резолюции (по пользователю ERP или его `crm_user_id`)."""
    _require_staff(user)
    tasks = CalcTask.objects.select_related("deal__company", "deal__stage", "deal__manager").order_by(
        "deal_id", "-decided_at", "-id"
    )
    if scope == "open":
        tasks = tasks.filter(deal__stage__code__in=OPEN_STAGES)
    if mine:
        crm_ids = _mapped_crm_ids(user)
        tasks = tasks.filter(Q(assignees__user=user) | Q(assignees__crm_user_id__in=crm_ids)).distinct()
    latest: dict[int, CalcTask] = {}
    for task in tasks[: MAX_ROWS * 3]:
        latest.setdefault(task.deal_id, task)
    rows = []
    for task in sorted(latest.values(), key=lambda t: (t.due, t.deal_id))[:MAX_ROWS]:
        deal = task.deal
        quote = calc_quote(deal)
        items = _billable(quote)
        ctx = _context(items)
        groups = _groups(items, ctx)
        rows.append(
            {
                "deal": _deal_brief(deal),
                "letter_number": task.letter_number,
                "due": task.due.isoformat(),
                "state": _calc_state(quote),
                "lines": len(items),
                "visas": {name: groups[name]["state"] for name in VISA_GROUPS},
                "assignees": _assignees(task),
            }
        )
    return rows


# ── экран расчёта ──────────────────────────────────────────────────────────────────────────────────────────────────


def sheet(deal_id: int, user) -> dict:
    """Экран «Расчёт по заявке»: заявка, задание, КП, строки, итоги без НДС, визы, готовность."""
    _require_staff(user)
    deal = _deal_or_404(deal_id)
    task = _task_or_404(deal)
    return _sheet(deal, task, user)


def _sheet(deal: Deal, task: CalcTask, user) -> dict:
    from .draft_quote import deal_request_lines_count, deal_request_text
    from .quotes.editable import quote_edit_lock_code

    quote = calc_quote(deal)
    items = _billable(quote)
    ctx = _context(items)
    show_cost = has_perm(user, Permission.QUOTE_VIEW_COST_MARGIN.value)
    rights = zone_rights(user)
    editable = quote is not None and quote_edit_lock_code(quote) is None
    lines = [line_payload(it, ctx, show_cost=show_cost, rights=rights, editable=editable) for it in items]
    purchase = sum((it.landed_cost * it.quantity for it in items), Decimal("0"))
    client = sum((it.final_price_excl_vat * it.quantity for it in items), Decimal("0"))
    groups = _groups(items, ctx)
    missing = sum(1 for line in lines if line["visa"] is None)
    if not editable:
        blocker = "not_draft" if quote is not None else "not_started"
    elif not lines:
        blocker = "no_lines"
    elif missing:
        blocker = "visas_missing"
    else:
        blocker = None
    return {
        "deal": _deal_brief(deal),
        "task": {**_task_brief(task), "assignees": _assignees(task)},
        "request": {"text": deal_request_text(deal), "lines": deal_request_lines_count(deal)},
        "quote": (
            None
            if quote is None
            else {
                "id": quote.id,
                "version": quote.version,
                "number": quote.number or None,
                "state": _calc_state(quote),
                "director_comment": quote.director_comment or None,
                "vat_rate": f"{quote.vat_rate:.2f}",
            }
        ),
        "lines": lines,
        "totals": {
            "purchase": _money(purchase),
            "client": _money(client),
            "markup_pct": _markup(purchase, client),
            "vat_included": False,
        },
        "visas": {name: groups[name] for name in VISA_GROUPS},
        "ready": {"allowed": blocker is None, "blocker": blocker, "missing": missing},
        "rights": {
            "goods": rights[Zone.GOODS],
            "services": rights[Zone.SERVICES],
            "build": has_perm(user, Permission.QUOTE_BUILD.value),
            "cost": show_cost,
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
                    detail=f"Черновик КП расчёта по {task.letter_number}",
                    user=user,
                    level="INFO",
                    entity_type="deal",
                    entity_id=deal.id,
                    deal=deal,
                    company_id=deal.company_id,
                    event_code="calc.started",
                    event_params={"letter_number": task.letter_number},
                )
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
    quantity: int = 1
    unit: str = ""
    kind: str = CalcLineKind.GOODS
    product_id: Optional[int] = None
    article: str = ""
    note: str = ""


def _product(product_id: Optional[int]):
    from catalog.models import Product

    if not product_id:
        return None
    product = Product.objects.select_related("domain_type").filter(pk=product_id).first()
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


def _recalc(quote: Quote) -> None:
    from .quotes import QuoteCalculationService

    QuoteCalculationService.recalculate_quote(quote.id)


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
            quantity=max(1, int(row.quantity or 1)),
            unit=(row.unit or "").strip()[:32],
            mpn=(row.article or "").strip()[:120],
            note=(row.note or "").strip(),
        )
        if quote.cost_currency_default_id:
            item.frozen_currency_id = quote.cost_currency_default_id
        _prefill_from_offer(item, product)
        item.save(skip_recalculate=True)
        CalcLine.objects.create(
            item=item, kind=CalcLineKind.SERVICE if row.kind == CalcLineKind.SERVICE else CalcLineKind.GOODS
        )
        created.append(item.id)
    _recalc(quote)
    _log(
        deal,
        user,
        "Строки добавлены в расчёт",
        f"{len(created)} строк(и) в расчёт по {task.letter_number}",
        "calc.lines_added",
        {"count": len(created), "letter_number": task.letter_number},
    )
    return {"created": created, **_sheet(deal, task, user)}


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
    "lead_days",
    "purchase_price",
    "purchase_currency",
    "crew_rate",
    "crew_days",
    "client_price",
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

    if "product_id" in changes:
        product = _product(changes["product_id"])
        new_zone = (Zone.SERVICES if product.is_service else Zone.GOODS) if product is not None else zone
        _require_zone(user, new_zone)
        if item.offer_id and (product is None or item.offer.product_id != product.id):
            item.offer = None
        item.product = product
        if product is not None:
            _prefill_from_offer(item, product)
        zone = new_zone
    if "kind" in changes:
        if item.product_id:
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
    if "name" in changes:
        name = (changes["name"] or "").strip()
        if not name:
            raise CalcError("NAME_REQUIRED", 400)
        item.imported_raw_name = name[: QuoteItem._meta.get_field("imported_raw_name").max_length]
    if "quantity" in changes:
        item.quantity = int(changes["quantity"])
    if "unit" in changes:
        item.unit = (changes["unit"] or "").strip()[:32]
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
        item.frozen_currency = _currency("UZS") if _has_currency("UZS") else None
    _reset_visa(calc)
    calc.save()
    item.version = (item.version or 0) + 1
    item.save()  # пересчёт КП с курсами строк — в QuoteItem.save
    if "client_price" in changes:
        _require(user, Permission.QUOTE_EDIT_PRICING.value)
        item.refresh_from_db()
        item.margin_percent = _markup_for(item, Decimal(str(changes["client_price"])))
        item.save()
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
    item.delete()
    _recalc(quote)
    _log(deal, user, "Строка удалена из расчёта", f"«{name}»", "calc.line_deleted", {"item_id": item_id})
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
    if calc.visa_at is not None and calc.visa_zone == zone:
        return _sheet(deal, task, user)
    if (item.landed_cost or 0) <= 0 or (item.final_price_excl_vat or 0) <= 0:
        raise CalcError("LINE_INCOMPLETE", 409)
    calc.visa_by = user
    calc.visa_by_name = person_name(user)[:255]
    calc.visa_zone = zone
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
    calc = calc_of(item)
    return calc is not None and calc.visa_at is not None and calc.visa_zone == zone_of(item)


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
            message=f"Расчёт по {task.letter_number}: все визы собраны, можно нажать «Расчёт готов».",
            link=f"#deal/{deal.id}",
            event_code="calc.all_signed",
            event_params={"deal_id": deal.id, "letter_number": task.letter_number},
        )
        push_notification_ws(notification)


# ── «Расчёт готов → черновик КП директору» ─────────────────────────────────────────────────────────────────────────


@transaction.atomic
def mark_ready(deal_id: int, user) -> dict:
    """Все строки завизированы → КП на одобрение директору в EDS (`quote.ready_for_approval`), КП «На утверждении».

    Проверки — как у отправки КП на согласование (`submit_for_review`): клиент заявки, ненулевая сумма, курсы строк,
    не в убыток. Визы строк заменяют визы КП: цепочка шагов ERP не строится."""
    from sales.services.quote_fx import fix_quote_rates, live_rates_outdated

    from .eds_quote_approval import request_director_approval
    from .quotes._shared import _set_quote_status
    from .quotes.lifecycle_gates import assert_submittable, resolve_submit_company
    from .quotes.pricing import compute_quote_economics

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _locked_deal_or_404(deal_id)
    task = _task_or_404(deal)
    quote = _draft_or_409(deal)
    items = _billable(quote)
    if not items:
        raise CalcError("NO_LINES", 409)
    missing = [it.id for it in items if not _signed(it)]
    if missing:
        raise CalcError("VISAS_MISSING", 409, missing=len(missing))
    company_id, err = resolve_submit_company(quote, user)
    if err:
        raise CalcError(err, 403 if err == "ROLE_NOT_PERMITTED" else 409)
    if live_rates_outdated(quote):
        _recalc(quote)
        quote.refresh_from_db()
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
    request_director_approval(quote, user)
    _log(
        deal,
        user,
        "Расчёт готов: черновик КП у директора",
        f"{quote.number or 'КП'} по {task.letter_number}: все визы собраны",
        "calc.ready",
        {"letter_number": task.letter_number, "number": quote.number, "lines": len(items)},
    )
    return _sheet(deal, task, user)


def line_visas(quote: Quote) -> list[tuple[str, Any, Any]]:
    """Визы строк КП для события `quote.ready_for_approval`: (зона, пользователь, время) — последняя виза человека в
    зоне. Пусто — КП собиралось без расчёта по строкам (визы — шагами КП)."""
    rows: dict[tuple[str, int], tuple[str, Any, Any]] = {}
    for item in quote.items.billable().select_related("calc__visa_by", "product__domain_type"):
        calc = calc_of(item)
        if calc is None or calc.visa_at is None or calc.visa_by_id is None or calc.visa_zone != zone_of(item):
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
    каждое слово запроса. Детерминированно, без ИИ; человек выбирает карточку сам."""
    from catalog.models import Product

    _require_staff(user)
    words = [w for w in (q or "").split() if w][:6]
    if not words:
        return []
    qs = Product.objects.select_related("domain_type").exclude(status__code="ARCHIVED")
    for word in words:
        qs = qs.filter(
            Q(name__icontains=word)
            | Q(sku__icontains=word)
            | Q(manufacturer_part_number__icontains=word)
            | Q(gost_drawing__icontains=word)
        )
    products = list(qs.order_by("name")[:limit])
    own = _own_offers([p.id for p in products])
    suppliers = _supplier_offers([p.id for p in products])
    rows = []
    for product in products:
        offer = suppliers.get(product.id)
        stock = own.get(product.id)
        rows.append(
            {
                "id": product.id,
                "name": product.name,
                "article": product.manufacturer_part_number or product.sku,
                "kind": "service" if product.is_service else "goods",
                "on_hand": stock.stock_quantity if stock is not None else 0,
                "supplier_name": offer.supplier.name if offer is not None else None,
                "lead_days": (offer.order_lead_time_days or offer.in_stock_lead_time_days or None) if offer else None,
            }
        )
    return rows


def parse_payload(deal_id: int, user, text: Optional[str]) -> dict:
    """Проверки перед ИИ-разбором (дешёвые, до очереди): заявка с заданием, право строить КП, есть текст."""
    from .draft_quote import deal_request_text

    _require_staff(user)
    _require(user, Permission.QUOTE_BUILD.value)
    deal = _deal_or_404(deal_id)
    _task_or_404(deal)
    source = (text or "").strip() or deal_request_text(deal)
    if not source:
        raise CalcError("REQUEST_TEXT_EMPTY", 409)
    return {"deal_id": deal.id, "user_id": user.pk, "text": source[:20000]}


def parse_proposal(text: str) -> dict:
    """ИИ-разбор текста заявки в строки — ПРЕДЛОЖЕНИЕ: ничего не записывается, строки добавляет человек
    (`add_lines`). Модель — через шлюз ИИ по алиасу (`ai.services.intake`)."""
    from ai.services.intake import extract_request_items

    try:
        rows = extract_request_items(text.encode("utf-8"), "request.txt")
    except (RuntimeError, ValueError) as exc:
        logger.warning("AI calc parse failed: %s", exc)
        return {"error": "AI_DISABLED" if str(exc).startswith("AI_IMPORT_DISABLED") else "AI_EXTRACT_FAILED"}
    proposal = []
    for row in rows[:MAX_LINES_PER_CALL]:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            quantity = max(1, int(Decimal(str(row.get("quantity") or 1)).to_integral_value(rounding="ROUND_CEILING")))
        except (ArithmeticError, ValueError):
            quantity = 1
        proposal.append(
            {
                "name": name[:500],
                "quantity": quantity,
                "unit": str(row.get("unit") or "")[:32],
                "article": str(row.get("mpn") or row.get("gost_drawing") or "")[:120],
                "note": str(row.get("note") or "")[:1000],
            }
        )
    return {"proposal": proposal, "recognized": len(rows), "truncated": len(rows) > MAX_LINES_PER_CALL}
