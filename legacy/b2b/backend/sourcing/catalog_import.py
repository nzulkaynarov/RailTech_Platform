"""Self-service seller catalog import engine (true-PIM).

A seller uploads an .xlsx of their products + commercial terms. We:
  * resolve/create the **Brand** (catalog.Manufacturer) by name,
  * de-duplicate the canonical **Product** by (brand + manufacturer part number)
    or GOST/drawing — so two suppliers of the same item share ONE PIM card,
  * upsert the seller's **SupplierOffer** (price / currency / stock / lead / MOQ).

The supplier is the UPLOADER's own company (derived from membership in the
view) — never a column in the file. Each row is processed in its own savepoint
so one bad row can't poison the batch; per-row problems are returned as a
structured error list. `dry_run=True` runs the full pipeline and rolls back,
returning the same counts for a preview.

Business logic lives here (Rule 8); the Celery task is a thin wrapper.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pandas as pd
from django.db import transaction

logger = logging.getLogger(__name__)

MAX_EXCEL_ROWS = 50_000
MAX_REPORTED_ERRORS = 200

# Logical field -> substring aliases (matched against lower-cased headers).
# Order matters: more specific fields claim their column before generic ones
# (e.g. "артикул производителя" is taken by `mpn`, leaving bare "артикул" for
# `supplier_sku`).
# NOTE: resolution order matters — the more specific identifier columns (mpn,
# gost, supplier_sku) claim their column BEFORE `brand`, because the brand alias
# "производитель" is a substring of "артикул производителя" (MPN) and would
# otherwise steal it.
COLUMN_ALIASES = {
    "name": ["name", "наименование", "товар", "название", "изделие"],
    "mpn": ["артикул производителя", "mpn", "part number", "part_no", "заводской", "номер детали"],
    "gost": ["гост", "gost", "чертеж", "drawing"],
    "supplier_sku": ["артикул поставщика", "supplier sku", "ваш артикул", "артикул продавца", "артикул"],
    "brand": ["бренд", "brand", "производитель", "manufacturer", "марка"],
    "description": ["описание", "desc", "примечание"],
    "uom": ["ед", "изм", "uom", "unit"],
    "price": ["цена", "price", "стоимость"],
    "currency": ["валюта", "currency"],
    "stock": ["наличие", "склад", "stock"],
    "lead": ["срок", "lead", "поставк"],
    "moq": ["мин", "moq", "минимальн"],
}


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    offers_upserted: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)
    dry_run: bool = False

    def add_error(self, row_number: int, message: str) -> None:
        self.skipped += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append({"row": row_number, "message": message})

    def as_dict(self) -> dict:
        return {
            "status": "success",
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "offers_upserted": self.offers_upserted,
            "skipped": self.skipped,
            "error_count": self.skipped,
            "errors": self.errors,
            # Backward-compatible key consumed by the existing frontend.
            "items_processed": self.created + self.updated,
        }


def _resolve_columns(columns) -> dict:
    """Map each logical field to an actual column, claiming each column once."""
    resolved = {}
    claimed = set()
    for logical, aliases in COLUMN_ALIASES.items():
        for column in columns:
            if column in claimed:
                continue
            if any(alias in column for alias in aliases):
                resolved[logical] = column
                claimed.add(column)
                break
        else:
            resolved[logical] = None
    return resolved


def _cell(row, column) -> str:
    """Trimmed string for a cell; '' for missing/NaN."""
    if not column:
        return ""
    value = row.get(column)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _parse_decimal(text: str):
    """Parse a price cell. Returns None for a blank cell (name-only row → no offer).

    A non-blank value must be a number > 0 — a negative or zero price is a data
    error, not a valid offer (M3). We reject it with a stable code so the row is
    rolled back and reported instead of silently writing a bogus offer.
    """
    if not text:
        return None
    try:
        value = Decimal(text.replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("PRICE_NOT_A_NUMBER")
    if value <= 0:
        raise ValueError("PRICE_NOT_POSITIVE")
    return value


def _parse_int(text: str, default: int) -> int:
    if not text:
        return default
    try:
        return int(float(text.replace(" ", "").replace(",", ".")))
    except (ValueError, TypeError):
        return default


@dataclass
class _Ctx:
    """Per-import shared state (caches + lookups) — avoids per-row DB queries."""

    supplier: object
    Product: object
    Manufacturer: object
    SupplierOffer: object
    uom: dict
    currency: dict
    stock: dict
    domain: dict
    status_draft: object
    brand_cache: dict
    dry_run: bool


def _resolve_brand(ctx: _Ctx, name: str):
    """Find a Brand by name, creating it on demand (catalog grows from uploads).

    In dry-run we never create — an unseen brand resolves to None, which only
    softens product de-dup for the preview.
    """
    if not name:
        return None
    key = name.lower()
    if key in ctx.brand_cache:
        return ctx.brand_cache[key]
    brand = ctx.Manufacturer.objects.filter(name__iexact=name).first()
    if not brand and not ctx.dry_run:
        brand = ctx.Manufacturer.objects.create(name=name)
    ctx.brand_cache[key] = brand
    return brand


def _find_existing_product(ctx: _Ctx, brand, mpn: str, gost: str):
    """De-dup key: (brand + manufacturer part number), else GOST/drawing."""
    if brand and mpn:
        return ctx.Product.objects.filter(brand=brand, manufacturer_part_number__iexact=mpn).first()
    if gost:
        query = ctx.Product.objects.filter(gost_drawing__iexact=gost)
        if brand:
            query = query.filter(brand=brand)
        return query.first()
    return None


def _apply_product(ctx: _Ctx, fields: dict):
    """Create or update the canonical Product card. Returns (product, created)."""
    from .tasks import route_domain

    brand = _resolve_brand(ctx, fields["brand_name"])
    existing = _find_existing_product(ctx, brand, fields["mpn"], fields["gost"])
    domain = ctx.domain.get(route_domain(fields["name"]))
    uom = ctx.uom.get(fields["uom_code"]) if fields["uom_code"] else None

    if existing:
        existing.name = fields["name"]
        if fields["description"]:
            existing.description = fields["description"]
        if brand:
            existing.brand = brand
        if fields["mpn"]:
            existing.manufacturer_part_number = fields["mpn"]
        if fields["gost"]:
            existing.gost_drawing = fields["gost"]
        if uom:
            existing.uom = uom
        # Backfill ownership for an orphaned card (C3), but never hijack a product
        # another tenant already owns — de-dup matches globally on brand+MPN.
        if ctx.supplier and existing.owner_company_id is None:
            existing.owner_company = ctx.supplier
        existing.save()
        return existing, False

    product = ctx.Product.objects.create(
        name=fields["name"],
        description=fields["description"],
        brand=brand,
        manufacturer_part_number=fields["mpn"],
        gost_drawing=fields["gost"],
        domain_type=domain,
        status=ctx.status_draft,
        uom=uom,
        # Stamp the importing seller as owner so they can see/manage their own cards
        # (C3) — without this, imported products are orphaned and invisible to them.
        owner_company=ctx.supplier,
    )
    return product, True


def _upsert_offer(ctx: _Ctx, product, offer: dict) -> None:
    """Upsert the uploader's SupplierOffer for this product (unique per supplier)."""
    ctx.SupplierOffer.objects.update_or_create(
        product=product,
        supplier=ctx.supplier,
        defaults={
            "base_price": offer["price"],
            "currency": offer["currency"],
            "stock_status": offer["stock"],
            "supplier_sku": offer["supplier_sku"],
            "delivery_lead_time": offer["lead"],
            "min_order_qty": offer["moq"],
            "is_active": True,
        },
    )


def _process_one_row(ctx: _Ctx, row, columns: dict):
    """Handle a single row. Returns an outcome dict, or None for a blank row.

    Raises ValueError with a stable code for row-level problems so the caller
    can roll back this row's savepoint and report it.
    """
    name = _cell(row, columns["name"])
    if not name:
        return None

    currency_code = _cell(row, columns["currency"]).upper()
    currency = ctx.currency.get(currency_code) if currency_code else None
    if currency_code and not currency:
        raise ValueError(f"UNKNOWN_CURRENCY:{currency_code}")

    stock_code = _cell(row, columns["stock"]).upper()
    stock = ctx.stock.get(stock_code) if stock_code else None
    if stock_code and not stock:
        raise ValueError(f"UNKNOWN_STOCK_STATUS:{stock_code}")

    price = _parse_decimal(_cell(row, columns["price"]))

    product, created = _apply_product(
        ctx,
        {
            "name": name,
            "description": _cell(row, columns["description"]),
            "brand_name": _cell(row, columns["brand"]),
            "mpn": _cell(row, columns["mpn"]),
            "gost": _cell(row, columns["gost"]),
            "uom_code": _cell(row, columns["uom"]).lower(),
        },
    )

    offer_written = False
    if ctx.supplier and price is not None:
        _upsert_offer(
            ctx,
            product,
            {
                "price": price,
                "currency": currency,
                "stock": stock,
                "supplier_sku": _cell(row, columns["supplier_sku"]),
                "lead": _cell(row, columns["lead"]),
                "moq": _parse_int(_cell(row, columns["moq"]), 1),
            },
        )
        offer_written = True

    return {"created": created, "offer": offer_written}


def _build_context(supplier, dry_run: bool) -> _Ctx:
    from catalog.models import DomainType, Manufacturer, Product, ProductStatus, StockStatus, SupplierOffer
    from master_data.models import Currency, UnitOfMeasure

    return _Ctx(
        supplier=supplier,
        Product=Product,
        Manufacturer=Manufacturer,
        SupplierOffer=SupplierOffer,
        uom={u.code.lower(): u for u in UnitOfMeasure.objects.all()},
        currency={c.code.upper(): c for c in Currency.objects.all()},
        stock={s.code.upper(): s for s in StockStatus.objects.all()},
        domain={d.code: d for d in DomainType.objects.all()},
        status_draft=ProductStatus.objects.filter(code="DRAFT").first(),
        brand_cache={},
        dry_run=dry_run,
    )


def _iterate_rows(ctx: _Ctx, data_frame, columns: dict, result: ImportResult, progress_callback) -> None:
    total = len(data_frame)
    for index, row in data_frame.iterrows():
        row_number = index + 2  # +1 for header, +1 for 1-based display
        try:
            with transaction.atomic():
                outcome = _process_one_row(ctx, row, columns)
        except ValueError as exc:
            result.add_error(row_number, str(exc))
            continue
        except Exception:  # noqa: BLE001 — isolate one row, keep importing
            logger.exception("Catalog import row %s failed", row_number)
            result.add_error(row_number, "ROW_FAILED")
            continue

        if outcome is None:
            continue
        if outcome["created"]:
            result.created += 1
        else:
            result.updated += 1
        if outcome["offer"]:
            result.offers_upserted += 1

        processed = result.created + result.updated + result.skipped
        if progress_callback and processed % 500 == 0:
            progress_callback(processed, total)


def run_catalog_import(file_content: bytes, supplier_company_id=None, dry_run=False, progress_callback=None) -> dict:
    """Parse an .xlsx and upsert PIM products + the uploader's offers.

    Returns a structured result dict (see ImportResult.as_dict). Raises
    ValueError('NAME_COLUMN_NOT_FOUND') when the file has no recognizable name
    column — the only fatal, file-level error.
    """
    from accounts.models import Company

    supplier = Company.objects.filter(id=supplier_company_id).first() if supplier_company_id else None

    data_frame = pd.read_excel(BytesIO(file_content), nrows=MAX_EXCEL_ROWS)
    data_frame.columns = [str(column).lower().strip() for column in data_frame.columns]
    columns = _resolve_columns(list(data_frame.columns))
    if not columns["name"]:
        raise ValueError("NAME_COLUMN_NOT_FOUND")

    ctx = _build_context(supplier, dry_run)
    result = ImportResult(dry_run=dry_run)

    if dry_run:
        with transaction.atomic():
            _iterate_rows(ctx, data_frame, columns, result, progress_callback)
            transaction.set_rollback(True)
    else:
        _iterate_rows(ctx, data_frame, columns, result, progress_callback)

    return result.as_dict()
