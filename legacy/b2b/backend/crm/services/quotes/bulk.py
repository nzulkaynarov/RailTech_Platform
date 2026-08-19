"""Bulk create/update of КП line items and manual product re-match.

Split out of the monolithic ``crm/services/quotes.py`` (ARCH refactor) — behaviour
unchanged. All-or-nothing transactional batch writes that mirror the single-item PATCH
guards and recalc discipline (one cascade via ``pricing.QuoteCalculationService``).
"""

from typing import Optional, Tuple

from django.db import transaction

from accounts.models import CustomUser
from crm.models import ActivityLog, Quote, QuoteItem
from crm.services.availability import resolve_seller_offer, split_line_by_availability

from ._shared import _quote_owner_company_id
from .pricing import QuoteCalculationService

# Fields the КП builder grid may write per line (the exact set the single-item PATCH accepts
# from handleSave). id/quote address the row; everything else is a pricing/identity input the
# QuoteItemSerializer validates (caps, currency-by-code). Anything outside this set is ignored.
_BULK_ITEM_WRITABLE_FIELDS = frozenset(
    {
        "quantity",
        "frozen_base_price",
        "frozen_currency",
        "logistics_cost",
        "customs_duty",
        "margin_percent",
        "discount_percent",
        "lead_time_days",
        "hs_code",
        # S1: display_type / optionality / explicit row order (reorder + section grouping).
        "display_type",
        "is_optional",
        "position",
    }
)


def _validate_bulk_item_rows(quote, items_payload, request):
    """Validate every payload row against the quote's OWN items (partial serializer).

    Returns (validated, rows): `validated` is a list of (item, validated_data) pairs when
    ALL rows are valid; `rows` is the per-row error list (empty ⇒ success). A row whose id
    is missing / not an item of THIS quote is itself an error — so the all-or-nothing policy
    also rejects a batch that mixes in a competitor's / phantom line."""
    from crm.serializers import QuoteItemSerializer

    existing = {item.id: item for item in quote.items.all()}
    validated: list = []
    rows: list = []
    for index, raw in enumerate(items_payload):
        item_id = raw.get("id") if isinstance(raw, dict) else None
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            rows.append(
                {
                    "id": raw.get("id") if isinstance(raw, dict) else None,
                    "index": index,
                    "errors": {"id": ["QUOTE_ITEM_ID_REQUIRED"]},
                }
            )
            continue
        item = existing.get(item_id)
        if item is None:
            rows.append({"id": item_id, "index": index, "errors": {"id": ["QUOTE_ITEM_NOT_IN_QUOTE"]}})
            continue
        # Optimistic-concurrency check (волна 3): if the row carries the version the frontend last
        # read, it MUST match the DB — otherwise a colleague saved this line in the meantime and
        # applying our stale edit would silently clobber theirs. A mismatch is a per-row error in
        # the SAME rows[].errors shape as a validation error (version → QUOTE_ITEM_STALE), so the
        # all-or-nothing policy rolls the whole batch back (nothing partially applied on conflict).
        # `version` is OPTIONAL for backward compatibility — a payload that omits it skips the
        # check entirely (last-write-wins, pre-волна-3 behaviour).
        payload_version = raw.get("version")
        if payload_version is not None:
            try:
                payload_version = int(payload_version)
            except (TypeError, ValueError):
                payload_version = None
            if payload_version is None or payload_version != item.version:
                rows.append({"id": item_id, "index": index, "errors": {"version": ["QUOTE_ITEM_STALE"]}})
                continue
        fields = {key: value for key, value in raw.items() if key in _BULK_ITEM_WRITABLE_FIELDS}
        serializer = QuoteItemSerializer(instance=item, data=fields, partial=True, context={"request": request})
        if not serializer.is_valid():
            rows.append({"id": item_id, "index": index, "errors": serializer.errors})
            continue
        validated.append((item, serializer.validated_data))
    return validated, rows


@transaction.atomic
def bulk_update_quote_items(user, quote_id, items_payload, request):
    """Transactional bulk update of a КП's line items (P0-4). ALL-OR-NOTHING.

    Mirrors the single-item PATCH guards EXACTLY (is_platform_admin_viewer / seller pricing
    capability / seller-routed-to-deal), validates every row with the same QuoteItemSerializer
    (caps included), and — on full success — writes once and recalculates the cascade ONCE
    (recalculate_quote also snapshots QuoteItemHistory, so the audit trail matches the single
    PATCH). Any invalid row rolls the whole batch back with per-row errors.

    Returns (items, error, rows):
      • success        → (list[QuoteItem], None, None)
      • guard/global   → (None, "<CODE>", None)
      • per-row invalid→ (None, "QUOTE_ITEMS_BULK_INVALID", [ {id,index,errors}, … ])
    """
    from accounts.services.permissions import can_edit_quote_pricing, is_platform_admin_viewer, seller_can_access_deal

    # Guards — IN THE SAME ORDER as QuoteItemViewSet._assert_seller.
    if is_platform_admin_viewer(user):
        return None, "ADMIN_VIEWER_CANNOT_ACT", None
    is_superuser = getattr(user, "is_superuser", False)
    if not (is_superuser or can_edit_quote_pricing(user)):
        return None, "ONLY_SELLER_CAN_BUILD_QUOTE", None

    if not isinstance(items_payload, list) or not items_payload:
        return None, "QUOTE_ITEMS_BULK_EMPTY", None
    from django.conf import settings

    if len(items_payload) > settings.QUOTE_ITEMS_BULK_MAX_ROWS:
        return None, "QUOTE_ITEMS_BULK_TOO_LARGE", None

    try:
        quote_pk = int(quote_id)
    except (TypeError, ValueError):
        return None, "QUOTE_NOT_FOUND", None
    # Lock only the quote row (nullable FKs can't be FOR UPDATE'd via join — mirror recalc).
    quote = Quote.objects.select_for_update(of=("self",)).filter(pk=quote_pk).first()
    if quote is None:
        return None, "QUOTE_NOT_FOUND", None
    # Deal-routing binding (mirror _assert_seller_owns_quote_deal): a foreign КП is 404 like the
    # single PATCH, whose scoped get_queryset would never surface a competitor's item.
    if not (is_superuser or seller_can_access_deal(user, request, quote.deal_id)):
        return None, "QUOTE_NOT_FOUND", None
    if quote.frozen_at:
        return None, "QUOTE_FROZEN", None

    validated, rows = _validate_bulk_item_rows(quote, items_payload, request)
    if rows:
        # transaction.atomic + returning here rolls back nothing was written — all-or-nothing.
        return None, "QUOTE_ITEMS_BULK_INVALID", rows

    updated_ids = []
    for item, validated_data in validated:
        for attr, value in validated_data.items():
            setattr(item, attr, value)
        # Bump the optimistic-concurrency counter on the successful save (волна 3). The next
        # save from another manager who read version N is now rejected as stale. The full save
        # (no update_fields) persists version alongside the recomputed price fields; the ONE
        # cascade below re-aggregates the КП but never touches version (bulk_update, not save).
        item.version = (item.version or 0) + 1
        # Defer per-row recalc — one full cascade recompute follows for the whole КП.
        item.save(skip_recalculate=True)
        updated_ids.append(item.id)

    # ONE recalculation of the whole КП: refreshes each line's landed/final price with the FX
    # map, re-aggregates subtotal/charges/VAT/total, and snapshots QuoteItemHistory for every
    # line — the same audit the single-item PATCH produces, but once instead of N times.
    QuoteCalculationService.recalculate_quote(quote_pk)

    items = list(
        QuoteItem.objects.filter(quote_id=quote_pk, id__in=updated_ids).select_related(
            "product", "product__domain_type", "quote", "offer", "offer__supplier", "frozen_currency"
        )
    )
    return items, None, None


# Fields an Excel-paste may provide per NEW line: the line's identity (name + code columns)
# plus the same pricing inputs bulk-update accepts. Read-only/derived columns (landed_cost,
# final_price) are ignored. The line ALWAYS carries a non-empty imported_raw_name — the paste's
# first column — enforced below before the serializer runs.
_BULK_CREATE_WRITABLE_FIELDS = frozenset(
    {
        "imported_raw_name",
        "name_canonical",
        "quantity",
        "unit",
        "unit_code",
        "mpn",
        "gost_drawing",
        "hs_code",
        "note",
        "frozen_base_price",
        "frozen_currency",
        "logistics_cost",
        "customs_duty",
        "margin_percent",
        "discount_percent",
        "lead_time_days",
        # S1: a pasted row is an ITEM by default; sections/notes/optionality + explicit order
        # come from the grid builder (Excel-paste never sets them → plain ITEM lines).
        "display_type",
        "is_optional",
        "position",
    }
)


def _validate_bulk_create_rows(quote, items_payload, request):
    """Validate every payload row as a NEW КП line (QuoteItemSerializer, create mode).

    Returns (validated, rows): `validated` is a list of validated_data dicts when ALL rows are
    valid; `rows` is the per-row error list (empty ⇒ success). Each row MUST carry a non-empty
    imported_raw_name (QUOTE_ITEM_NAME_REQUIRED) — a blank paste cell is a per-row error, not a
    phantom line. The line cost currency defaults to the КП's cost_currency_default when the row
    omits it (mirrors the builder's «Добавить строку» default). Rows have NO id yet, so per-row
    errors are keyed by index only — never a (non-existent) row id."""
    from crm.serializers import QuoteItemSerializer

    default_currency = quote.cost_currency_default.code if quote.cost_currency_default_id else None
    validated: list = []
    rows: list = []
    for index, raw in enumerate(items_payload):
        name = raw.get("imported_raw_name") if isinstance(raw, dict) else None
        if not isinstance(name, str) or not name.strip():
            rows.append({"index": index, "errors": {"imported_raw_name": ["QUOTE_ITEM_NAME_REQUIRED"]}})
            continue
        fields = {key: value for key, value in raw.items() if key in _BULK_CREATE_WRITABLE_FIELDS}
        # A new line inherits the КП's default cost currency unless the row itself picks one —
        # same default the single-item «Add line» applies (frozen_currency = cost_currency_default).
        if not fields.get("frozen_currency") and default_currency:
            fields["frozen_currency"] = default_currency
        # Bind the target quote SERVER-side (from the addressed КП), never a per-row body value.
        fields["quote"] = quote.id
        serializer = QuoteItemSerializer(data=fields, context={"request": request})
        if not serializer.is_valid():
            rows.append({"index": index, "errors": serializer.errors})
            continue
        validated.append(serializer.validated_data)
    return validated, rows


@transaction.atomic
def bulk_create_quote_items(user, quote_id, items_payload, request):
    """Transactional bulk create of КП line items (Excel-paste). ALL-OR-NOTHING.

    Mirrors bulk_update_quote_items EXACTLY on guards (is_platform_admin_viewer / seller pricing
    capability / seller-routed-to-deal 404 / frozen КП) and recalc discipline (write every line
    with skip_recalculate, then recalculate_quote ONCE — one cascade, one QuoteItemHistory
    snapshot pass). Every row is validated with the same QuoteItemSerializer as the single-item
    create (caps, currency-by-code); a non-empty imported_raw_name is required per row, the qty /
    price defaults come from the model (qty=1, base 0) and the cost currency defaults to the КП's
    cost_currency_default. Any invalid row rolls the whole batch back with per-row errors.

    Returns (items, error, rows):
      • success        → (list[QuoteItem], None, None)
      • guard/global   → (None, "<CODE>", None)
      • per-row invalid→ (None, "QUOTE_ITEMS_BULK_INVALID", [ {index,errors}, … ])
    """
    from accounts.services.permissions import can_edit_quote_pricing, is_platform_admin_viewer, seller_can_access_deal

    # Guards — IN THE SAME ORDER as QuoteItemViewSet._assert_seller / bulk_update_quote_items.
    if is_platform_admin_viewer(user):
        return None, "ADMIN_VIEWER_CANNOT_ACT", None
    is_superuser = getattr(user, "is_superuser", False)
    if not (is_superuser or can_edit_quote_pricing(user)):
        return None, "ONLY_SELLER_CAN_BUILD_QUOTE", None

    if not isinstance(items_payload, list) or not items_payload:
        return None, "QUOTE_ITEMS_BULK_EMPTY", None
    from django.conf import settings

    if len(items_payload) > settings.QUOTE_ITEMS_BULK_MAX_ROWS:
        return None, "QUOTE_ITEMS_BULK_TOO_LARGE", None

    try:
        quote_pk = int(quote_id)
    except (TypeError, ValueError):
        return None, "QUOTE_NOT_FOUND", None
    # Lock only the quote row (nullable FKs can't be FOR UPDATE'd via join — mirror recalc).
    quote = (
        Quote.objects.select_for_update(of=("self",))
        .select_related("cost_currency_default")
        .filter(pk=quote_pk)
        .first()
    )
    if quote is None:
        return None, "QUOTE_NOT_FOUND", None
    # Deal-routing binding (mirror _assert_seller_owns_quote_deal): a foreign КП is 404 like the
    # single POST, whose scoped get_queryset would never surface a competitor's quote.
    if not (is_superuser or seller_can_access_deal(user, request, quote.deal_id)):
        return None, "QUOTE_NOT_FOUND", None
    if quote.frozen_at:
        return None, "QUOTE_FROZEN", None

    validated, rows = _validate_bulk_create_rows(quote, items_payload, request)
    if rows:
        # transaction.atomic + returning here writes nothing — all-or-nothing.
        return None, "QUOTE_ITEMS_BULK_INVALID", rows

    # New lines land at the END of the КП: start after the current max position and hand each
    # row (that didn't pick its own position) the next slot, preserving paste order. Default
    # position=0 would otherwise collide with the backfilled first row and interleave the paste.
    from django.db.models import Max

    next_position = (quote.items.aggregate(mx=Max("position"))["mx"] or 0) + 1
    created_ids = []
    for validated_data in validated:
        if validated_data.get("position") is None:
            validated_data["position"] = next_position
            next_position += 1
        item = QuoteItem(**validated_data)
        # Defer per-row recalc — one full cascade recompute follows for the whole КП.
        item.save(skip_recalculate=True)
        created_ids.append(item.id)

    # ONE recalculation of the whole КП: prices each new line with the FX map, re-aggregates
    # subtotal/charges/VAT/total and snapshots QuoteItemHistory — once, not per row.
    QuoteCalculationService.recalculate_quote(quote_pk)

    items = list(
        QuoteItem.objects.filter(quote_id=quote_pk, id__in=created_ids)
        .select_related("product", "product__domain_type", "quote", "offer", "offer__supplier", "frozen_currency")
        .order_by("position", "id")
    )
    return items, None, None


@transaction.atomic
def bulk_delete_quote_items(user, quote_id, item_ids, request):
    """Транзакционное удаление нескольких строк КП. ВСЁ ИЛИ НИЧЕГО.

    До появления этого пути фронт слал N ПАРАЛЛЕЛЬНЫХ DELETE. Каждый запрос брал блокировку
    строки КП и пересчитывал каскад, поэтому четыре одновременных удаления стабильно ловили
    `deadlock detected` в Postgres: часть строк исчезала, часть оставалась, пользователь видел
    только «Operation failed» и не знал, что именно удалилось (найдено прогоном глазами 19-08).
    Здесь всё делается одной транзакцией, с ОДНОЙ блокировкой КП и ОДНИМ пересчётом — как уже
    устроены bulk_update_quote_items и bulk_create_quote_items.

    Возвращает (deleted_ids, error, rows):
      • успех          → (list[int], None, None)
      • гард/общая     → (None, "<CODE>", None)
      • чужие строки   → (None, "QUOTE_ITEMS_BULK_INVALID", [ {id, errors}, … ])
    """
    from accounts.services.permissions import can_edit_quote_pricing, is_platform_admin_viewer, seller_can_access_deal

    # Гарды — В ТОМ ЖЕ ПОРЯДКЕ, что у соседних массовых операций.
    if is_platform_admin_viewer(user):
        return None, "ADMIN_VIEWER_CANNOT_ACT", None
    is_superuser = getattr(user, "is_superuser", False)
    if not (is_superuser or can_edit_quote_pricing(user)):
        return None, "ONLY_SELLER_CAN_BUILD_QUOTE", None

    if not isinstance(item_ids, list) or not item_ids:
        return None, "QUOTE_ITEMS_BULK_EMPTY", None
    from django.conf import settings

    if len(item_ids) > settings.QUOTE_ITEMS_BULK_MAX_ROWS:
        return None, "QUOTE_ITEMS_BULK_TOO_LARGE", None

    try:
        quote_pk = int(quote_id)
        wanted = [int(raw_id) for raw_id in item_ids]
    except (TypeError, ValueError):
        return None, "QUOTE_NOT_FOUND", None

    quote = Quote.objects.select_for_update(of=("self",)).filter(pk=quote_pk).first()
    if quote is None:
        return None, "QUOTE_NOT_FOUND", None
    if not (is_superuser or seller_can_access_deal(user, request, quote.deal_id)):
        return None, "QUOTE_NOT_FOUND", None
    if quote.frozen_at:
        return None, "QUOTE_FROZEN", None

    # Чужая строка — не «молча пропустить»: продавец должен узнать, что удалил не то, что видел.
    present = set(QuoteItem.objects.filter(quote_id=quote_pk, id__in=wanted).values_list("id", flat=True))
    missing = [item_id for item_id in wanted if item_id not in present]
    if missing:
        return (
            None,
            "QUOTE_ITEMS_BULK_INVALID",
            [{"id": item_id, "errors": ["QUOTE_ITEM_NOT_IN_QUOTE"]} for item_id in missing],
        )

    from crm.signals import suppress_quote_item_recalc

    # Гасим пересчёт «на каждую строку» из post_delete: для пачки он лишний, а с ним удаление
    # четырёх строк давало пять пересчётов подряд.
    with suppress_quote_item_recalc():
        QuoteItem.objects.filter(quote_id=quote_pk, id__in=present).delete()
    # ОДИН пересчёт на всю пачку: цены, каскад начислений, НДС и итог — как в соседних массовых.
    QuoteCalculationService.recalculate_quote(quote_pk)
    return sorted(present), None, None


@transaction.atomic
def reassign_quote_item_product(
    quote_item_id: int,
    actor: CustomUser,
    product_id: Optional[int],
) -> Tuple[Optional[QuoteItem], Optional[str]]:
    """Allow manager to override Smart Match result by picking a different product."""
    from accounts.services import is_platform_admin_viewer
    from catalog.models import Product

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    item = QuoteItem.objects.select_for_update().select_related("quote").get(pk=quote_item_id)
    if item.quote.frozen_at:
        return None, "QUOTE_FROZEN_CANNOT_REASSIGN"
    if product_id:
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return None, "PRODUCT_NOT_FOUND"
        item.product = product
        # Inherit ТНВЭД from the product card unless ВЭД already set it manually
        # (the per-line override wins; we only fill an empty code).
        if not (item.hs_code or "").strip() and (product.hs_code or "").strip():
            item.hs_code = product.hs_code
        # Lead-time INHERITANCE (Track B): pull the срок from the seller's OWN offer for
        # this product, but ONLY when the seller hasn't manually set one (0/unset). The
        # per-line override always wins — mirrors the hs_code inheritance above.
        offer = resolve_seller_offer(product, _quote_owner_company_id(item.quote))
        if not item.lead_time_days and offer is not None:
            tranches = split_line_by_availability(product, item.quantity, offer)
            item.lead_time_days = max((tranche.lead_time_days for tranche in tranches), default=0)
    else:
        item.product = None
    item.save(update_fields=["product", "assigned_at", "hs_code", "lead_time_days"])
    # AI-калибровка: an explicit re-match is the seller's verdict on the AI candidate for this line.
    from crm.services.ai_telemetry import resolve_outcome_on_reassign

    resolve_outcome_on_reassign(item, product_id)
    ActivityLog.objects.create(
        action="Переназначен продукт в позиции КП",
        detail=f"QuoteItem #{item.id} → Product #{product_id}",
        user=actor,
        level="INFO",
        entity_type="quote",
        entity_id=item.quote_id,
        deal_id=item.quote.deal_id,
        company_id=item.quote.deal.company_id if item.quote.deal_id else None,
        event_code="quote.item_rematched",
        event_params={"item_id": item.id, "product_id": product_id},
    )
    return item, None


# Поля позиции КП, наследуемые из AI-извлечённой строки (маппинг extract → QuoteItem).
_IMPORT_QTY_MIN, _IMPORT_QTY_MAX = 1, 1_000_000


def import_extracted_lines_into_quote(quote: Quote, actor: CustomUser, rows: list) -> Tuple[int, bool, Optional[str]]:
    """Q2 (импорт файла в билдер) — WORKER-SAFE вставка AI-извлечённых строк в КП продавца.

    Зеркалит гейты bulk_create_quote_items, но БЕЗ request (вызывается из Celery-хендлера):
    продавцовая capability (can_edit_quote_pricing), routing к сделке (request-free
    seller_company_routed_to_deal), НЕ frozen КП, лимит строк. Строки без имени отбрасываются;
    свыше QUOTE_ITEMS_BULK_MAX_ROWS — обрезаются с флагом truncated (тупик №8: не молча).
    Позиции добавляются В КОНЕЦ (после max position), валюта = cost_currency_default КП (как
    ручное «Добавить строку»), затем ОДИН recalc. Возврат: (added, truncated, error_code)."""
    from django.conf import settings
    from django.db.models import Max

    from accounts.services.permissions import can_edit_quote_pricing, seller_company_routed_to_deal

    is_superuser = getattr(actor, "is_superuser", False)
    if not (is_superuser or can_edit_quote_pricing(actor)):
        return 0, False, "ONLY_SELLER_CAN_BUILD_QUOTE"
    if not (is_superuser or seller_company_routed_to_deal(actor, quote.deal_id)):
        return 0, False, "QUOTE_NOT_FOUND"
    if quote.frozen_at:
        return 0, False, "QUOTE_FROZEN"

    clean = [row for row in rows if isinstance(row, dict) and (row.get("name") or "").strip()]
    if not clean:
        return 0, False, "IMPORT_NO_LINES"
    truncated = len(clean) > settings.QUOTE_ITEMS_BULK_MAX_ROWS
    clean = clean[: settings.QUOTE_ITEMS_BULK_MAX_ROWS]

    def _qty(value):
        try:
            return max(_IMPORT_QTY_MIN, min(_IMPORT_QTY_MAX, int(value)))
        except (TypeError, ValueError):
            return 1

    default_currency = quote.cost_currency_default if quote.cost_currency_default_id else None
    with transaction.atomic():
        next_position = (quote.items.aggregate(mx=Max("position"))["mx"] or 0) + 1
        for offset, row in enumerate(clean):
            QuoteItem(
                quote=quote,
                imported_raw_name=(row.get("name") or "").strip()[:500],
                name_canonical=(row.get("name_canonical") or "").strip(),
                quantity=_qty(row.get("quantity", 1)),
                unit=(row.get("unit") or "").strip(),
                unit_code=(row.get("unit_code") or "").strip(),
                mpn=(row.get("mpn") or "").strip(),
                gost_drawing=(row.get("gost_drawing") or "").strip(),
                note=(row.get("note") or "").strip(),
                frozen_currency=default_currency,
                position=next_position + offset,
            ).save(skip_recalculate=True)
        QuoteCalculationService.recalculate_quote(quote.id)
    return len(clean), truncated, None
