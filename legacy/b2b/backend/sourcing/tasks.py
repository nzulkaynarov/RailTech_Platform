import base64
import logging
from io import BytesIO

import pandas as pd
from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import DomainKeyword
from .services import smart_match_product

logger = logging.getLogger(__name__)

# Safety limits for Excel processing. Enterprise clients upload catalogs with
# tens of thousands of lines — we allow up to 50k rows and write them in
# fixed-size DB batches to keep memory bounded and DB round-trips reasonable.
MAX_EXCEL_ROWS = 50_000
BULK_CHUNK = 1_000


def route_domain(text: str) -> str:
    """
    MED-2: Dynamic domain routing.
    Checks raw text against keywords stored in the database.
    """
    if not text:
        return "GENERAL_GOODS"

    text_lower = text.lower()

    # Cache keywords for 5 minutes to avoid DB pressure
    keywords = cache.get("sourcing_routing_keywords")
    if not keywords:
        # Structure: [(keyword_lower, domain_code), ...]
        keywords = list(DomainKeyword.objects.values_list("keyword", "domain_type__code"))
        # Handle case-insensitive matching by lowering keywords
        keywords = [(k.lower(), code) for k, code in keywords]
        cache.set("sourcing_routing_keywords", keywords, 300)

    for keyword, domain_code in keywords:
        if keyword in text_lower:
            return domain_code

    return "GENERAL_GOODS"


def _flush_catalog_chunk(Product, chunk):
    """Write one chunk of catalog rows in a single short transaction.

    Keeps update_or_create semantics (sku is the unique key). Chunk is a list
    of {sku, data} dicts prepared by the caller.
    """
    with transaction.atomic():
        for entry in chunk:
            if entry["sku"]:
                Product.objects.update_or_create(sku=entry["sku"], defaults=entry["data"])
            else:
                Product.objects.create(**entry["data"])


@shared_task(bind=True, time_limit=1800, soft_time_limit=1700)
def process_excel_import(self, deal_id: int, file_content_b64: str, user_id: int = None):
    """
    Processes uploaded Excel file and creates QuoteItems for the active Quote.
    Uses bulk_create to avoid O(n²) recalculation.
    file_content_b64: base64-encoded XLSX file content (JSON-safe).
    """
    from crm.models import Deal, Quote, QuoteItem, QuoteStatus

    try:
        file_content = base64.b64decode(file_content_b64)
        deal = Deal.objects.get(id=deal_id)

        # Ensure there's an active quote to add items to
        quote = deal.active_quote
        if not quote:
            draft_status = QuoteStatus.objects.filter(code="DRAFT").first()
            if not draft_status:
                return {"status": "error", "message": "QuoteStatus DRAFT not found. Run seed data."}
            next_version = (deal.quotes.aggregate(max_v=Max("version"))["max_v"] or 0) + 1
            quote, _created = Quote.objects.get_or_create(
                deal=deal,
                version=next_version,
                defaults={"status": draft_status},
            )

        df = pd.read_excel(BytesIO(file_content), nrows=MAX_EXCEL_ROWS)
        df.columns = [str(c).lower().strip() for c in df.columns]

        name_col = next((c for c in df.columns if "name" in c or "наименование" in c or "товар" in c), None)
        qty_col = next((c for c in df.columns if "qty" in c or "кол" in c or "quantity" in c), None)

        if not name_col:
            return {"status": "error", "message": "Could not find name column in Excel."}

        items_to_create = []
        total_rows = len(df)

        for idx, row in df.iterrows():
            raw_name = str(row[name_col]).strip()
            if not raw_name or raw_name == "nan" or raw_name == "":
                continue

            quantity = 1
            if qty_col and pd.notnull(row[qty_col]):
                try:
                    quantity = int(float(row[qty_col]))
                except (ValueError, TypeError):
                    pass

            domain_code = route_domain(raw_name)
            final_product = smart_match_product(raw_name, domain_hint=domain_code)

            items_to_create.append(
                QuoteItem(
                    quote=quote,
                    product=final_product,
                    imported_raw_name=raw_name,
                    quantity=quantity,
                    assigned_at=timezone.now() if final_product else None,
                )
            )

            if len(items_to_create) % 10 == 0 or (idx + 1) == total_rows:
                self.update_state(state="PROGRESS", meta={"current": len(items_to_create), "total": total_rows})

        if not items_to_create:
            return {"status": "error", "message": "Файл обработан, но не найдено ни одной строки."}

        # Bulk create in fixed-size batches. `batch_size` caps the number of
        # rows per INSERT so we don't explode Postgres parameter limits or
        # Celery worker memory on 10k+ row imports.
        with transaction.atomic():
            QuoteItem.objects.bulk_create(items_to_create, batch_size=BULK_CHUNK)

        # Single final recalculation of the entire quote
        quote.recalculate_totals()
        return {"status": "success", "items_processed": len(items_to_create)}

    except Deal.DoesNotExist:
        return {"status": "error", "message": "Deal not found."}
    except (ValueError, KeyError, TypeError, OSError):
        logger.exception("Excel import failed for deal %s", deal_id)
        return {"status": "error", "message": "Import failed. Please check the file format and try again."}


@shared_task(bind=True, time_limit=1800, soft_time_limit=1700)
def process_catalog_import(self, file_content_b64: str):
    """
    Processes uploaded Excel file to populate the global Product catalog (PIM).
    file_content_b64: base64-encoded XLSX file content (JSON-safe).
    """
    from catalog.models import DomainType, Product, ProductStatus
    from master_data.models import UnitOfMeasure

    try:
        file_content = base64.b64decode(file_content_b64)
        df = pd.read_excel(BytesIO(file_content), nrows=MAX_EXCEL_ROWS)
        df.columns = [str(c).lower().strip() for c in df.columns]

        def find_col(aliases, default):
            for c in df.columns:
                if any(alias in str(c).lower() for alias in aliases):
                    return c
            return default

        col_map = {
            "name": find_col(["name", "наименование", "товар", "название", "изделие"], "name"),
            "sku": find_col(["sku", "артикул", "чертеж", "номер"], "sku"),
            "description": find_col(["desc", "описание", "примечание"], "description"),
            "uom": find_col(["uom", "ед", "изм"], "uom"),
        }

        uom_cache = {u.code.lower(): u for u in UnitOfMeasure.objects.all()}
        # Cache domain types to avoid per-row DB queries
        domain_cache = {d.code: d for d in DomainType.objects.all()}
        status_draft = ProductStatus.objects.filter(code="DRAFT").first()

        items_processed = 0
        total_rows = len(df)
        # Process in chunks so a 50k-row import doesn't hold one giant
        # transaction open (which would bloat WAL and risk lock contention).
        chunk = []
        for idx, row in df.iterrows():
            raw_name = str(row.get(col_map["name"], "")).strip()
            if not raw_name or raw_name == "nan":
                continue

            sku = str(row.get(col_map["sku"], "")).strip()
            if sku == "nan":
                sku = None

            uom_code = str(row.get(col_map["uom"], "шт")).strip().lower()
            uom_obj = uom_cache.get(uom_code)

            domain_code = route_domain(raw_name)
            domain_obj = domain_cache.get(domain_code)

            chunk.append(
                {
                    "sku": sku,
                    "data": {
                        "name": raw_name,
                        "description": (
                            str(row.get(col_map["description"], "")).strip()
                            if row.get(col_map["description"]) != "nan"
                            else ""
                        ),
                        "domain_type": domain_obj,
                        "status": status_draft,
                        "uom": uom_obj,
                    },
                }
            )

            if len(chunk) >= BULK_CHUNK:
                _flush_catalog_chunk(Product, chunk)
                items_processed += len(chunk)
                chunk = []
                self.update_state(state="PROGRESS", meta={"current": items_processed, "total": total_rows})

        if chunk:
            _flush_catalog_chunk(Product, chunk)
            items_processed += len(chunk)
            self.update_state(state="PROGRESS", meta={"current": items_processed, "total": total_rows})

        return {"status": "success", "items_processed": items_processed}
    except (ValueError, KeyError, TypeError, OSError):
        logger.exception("Catalog import failed")
        return {"status": "error", "message": "Catalog import failed. Please check the file format and try again."}
