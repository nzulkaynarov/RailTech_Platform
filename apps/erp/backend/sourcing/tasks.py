import base64
import logging
from io import BytesIO

import pandas as pd
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .services import smart_match_product

logger = logging.getLogger(__name__)

# Safety limits for Excel processing. Enterprise clients upload catalogs with
# tens of thousands of lines — we allow up to 50k rows and write them in
# fixed-size DB batches to keep memory bounded and DB round-trips reasonable.
MAX_EXCEL_ROWS = 50_000
BULK_CHUNK = 1_000


def route_domain(text: str) -> str:
    """
    Default domain routing (GENERAL_GOODS). Keyword-based routing removed in M1-ERP-02 wave 4.
    """
    return "GENERAL_GOODS"


# Column-header synonyms across the formats real clients actually send
# (RU / UZ-Latin / UZ-Cyrillic / EN). Matching is substring + case-insensitive.
# Keep UNIT keywords specific so they don't swallow the name column.
_COL_KEYWORDS = {
    "name": [
        "наименование",
        "номенклатур",
        "название",
        "товар",
        "материал",
        "номи",
        "номланиш",
        "қисм",
        "эҳтиёт",
        "qism",
        "name",
        "description",
        "item",
        "mahsulot",
    ],
    "qty": [
        "кол-во",
        "колл",
        "кол.",
        "количество",
        "миқдор",
        "miqdor",
        "сони",
        "soni",
        "qty",
        "quantity",
        "amount",
        "адет",
    ],
    "unit": [
        "ед.изм",
        "ед изм",
        "ед.",
        "единиц",
        "ўлчов",
        "улчов",
        "бирлик",
        "бир-ги",
        "birlik",
        "o'lchov",
        "olchov",
        "unit",
        "uom",
        "measure",
    ],
    "note": [
        "примечан",
        "коммент",
        "izoh",
        "izoh",
        "note",
        "comment",
        "remark",
        "характеристик",
        "спецификац",
        "описание",
    ],
    "link": ["ссылка", "ссылк", "havola", "link", "url"],
    # Manufacturer Part Number / каталожный код. Kept narrow so it doesn't
    # swallow the name column ("товар"/"материал" live under "name" above and are
    # matched first, so their column is already taken before we look for article).
    "article": [
        "артикул",
        "артик",
        "artikul",
        "каталожн",
        "katalog",
        "kataloq",
        "mpn",
        "part no",
        "part num",
        "part#",
        "код произв",
    ],
}


def _cell(value) -> str:
    """Normalise a worksheet cell to a clean lowercase string ('' for blank/NaN)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _match_column(cells, keywords, taken):
    """First column index whose header cell contains any keyword and isn't taken."""
    for idx, raw in enumerate(cells):
        if idx in taken:
            continue
        low = _cell(raw).lower()
        if low and low != "unnamed" and not low.startswith("unnamed") and any(k in low for k in keywords):
            return idx
    return None


def detect_header_and_columns(raw_df):
    """Find the real header row (skip title banners) and map logical → column index.

    Real заявки often start with a merged title row and use RU/UZ/EN headers in
    any order, with extra Photo/Note/Link columns. A row is the header when it
    has BOTH a name-like cell AND a quantity- or unit-like cell in *different*
    columns — a single-cell title never qualifies. Returns (header_row_index,
    {name, qty, unit, note, article, link}) or (None, None) if nothing matches.
    """
    max_scan = min(len(raw_df), 15)
    for row_idx in range(max_scan):
        cells = list(raw_df.iloc[row_idx])
        taken: set = set()
        name_i = _match_column(cells, _COL_KEYWORDS["name"], taken)
        if name_i is None:
            continue
        taken.add(name_i)
        qty_i = _match_column(cells, _COL_KEYWORDS["qty"], taken)
        if qty_i is not None:
            taken.add(qty_i)
        unit_i = _match_column(cells, _COL_KEYWORDS["unit"], taken)
        if unit_i is not None:
            taken.add(unit_i)
        # A genuine header needs name + (qty or unit) in distinct columns.
        if qty_i is None and unit_i is None:
            continue
        note_i = _match_column(cells, _COL_KEYWORDS["note"], taken)
        if note_i is not None:
            taken.add(note_i)
        article_i = _match_column(cells, _COL_KEYWORDS["article"], taken)
        if article_i is not None:
            taken.add(article_i)
        link_i = _match_column(cells, _COL_KEYWORDS["link"], taken)
        return row_idx, {
            "name": name_i,
            "qty": qty_i,
            "unit": unit_i,
            "note": note_i,
            "article": article_i,
            "link": link_i,
        }
    return None, None


def _build_quote_item(
    quote, name, quantity, unit="", note="", unit_code="", mpn="", gost_drawing="", name_canonical=""
):
    """One place to turn a parsed/AI-extracted row into a QuoteItem — runs domain
    routing + smart-match so both the deterministic and the AI path behave the same.
    Smart-match runs on the name OR the identifier so name-less coded lines still try.

    name_canonical: the clean canonical RU name the AI paid to produce (билингва/
    транслитерация). When present we (a) store it on QuoteItem.name_canonical as the
    кириллический catalog-search key, and (b) show it to the buyer as the primary
    display name (imported_raw_name) instead of the dirty raw string. The verbatim
    original is kept as provenance in `note`. The deterministic parser passes ''."""
    from crm.models import QuoteItem

    canonical = (name_canonical or "").strip()
    raw_name = name or ""
    # Buyer's grid renders imported_raw_name → show the CLEAN value when the AI gave
    # us one; keep the verbatim original as provenance so nothing is silently lost.
    display_name = canonical or raw_name
    final_note = note or ""
    if canonical and raw_name and raw_name.strip() != canonical:
        provenance = f"Исходное наименование: {raw_name.strip()}"
        final_note = f"{final_note}\n{provenance}".strip() if final_note else provenance

    # Smart-match on the canonical (кириллица hits the catalog) → raw → identifier.
    match_key = canonical or raw_name or mpn or gost_drawing
    domain_code = route_domain(match_key)
    final_product = smart_match_product(match_key, domain_hint=domain_code) if match_key else None
    try:
        qty = max(1, int(float(quantity)))
    except (ValueError, TypeError):
        qty = 1
    return QuoteItem(
        quote=quote,
        product=final_product,
        imported_raw_name=display_name[:500],
        name_canonical=canonical[:500],
        quantity=qty,
        unit=(unit or "")[:32],
        unit_code=(unit_code or "")[:8],
        mpn=(mpn or "")[:120],
        gost_drawing=(gost_drawing or "")[:120],
        note=final_note,
        assigned_at=timezone.now() if final_product else None,
    )


@shared_task(
    bind=True,
    # Higher than the 600s default — enterprise imports can be 50k rows.
    time_limit=1800,
    soft_time_limit=1700,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_excel_import(
    self, deal_id: int, file_content_b64: str, user_id: int = None, use_ai: bool = False, filename: str = None
):
    """
    Turns an uploaded client file into QuoteItems on the deal's active Quote.

    Two paths to the same canonical schema (name/quantity/unit/note):
      • use_ai=True  → the model (LiteLLM, intake-model) reads ANY file (Excel/CSV/PDF/photo) and maps it
        (ai.services.intake). Falls back to the deterministic parser on failure.
      • use_ai=False → deterministic header-detect + keyword parser (xlsx only).

    The buyer reviews every recognised item before submitting, so the AI never
    writes a final заявка unattended. file_content_b64 is the base64 file (JSON-safe).
    """
    from crm.models import Deal, Quote, QuoteStatus

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

        items_to_create = []

        # ── AI path: any file → model (LiteLLM) → our schema (fallback to parser on error) ──
        ai_rows = None
        if use_ai and getattr(settings, "AI_IMPORT_ENABLED", False):
            try:
                from ai.services.context import trace_scope
                from ai.services.intake import extract_request_items

                # Трейс Langfuse и журнал вызовов: задача импорта, сотрудник — из аргументов задачи.
                with trace_scope(
                    str(self.request.id or f"import-deal-{deal_id}"), user_id=user_id, job_feature="intake"
                ):
                    ai_rows = extract_request_items(file_content, filename or "upload.xlsx")
                logger.info("AI import: deal=%s recognised %s items", deal_id, len(ai_rows))
            except Exception:  # noqa: BLE001 — an AI/API failure must never break the import (parser fallback)
                logger.exception("AI import failed deal=%s — falling back to deterministic parser", deal_id)
                ai_rows = None

        if ai_rows is not None:
            items_to_create = [
                _build_quote_item(
                    quote,
                    row.get("name", ""),
                    row.get("quantity", 1),
                    row.get("unit", ""),
                    row.get("note", ""),
                    unit_code=row.get("unit_code", ""),
                    mpn=row.get("mpn", ""),
                    gost_drawing=row.get("gost_drawing", ""),
                    name_canonical=row.get("name_canonical", ""),
                )
                for row in ai_rows
            ]
        else:
            # ── Deterministic path: detect header row + parse columns (xlsx) ──
            raw_df = pd.read_excel(BytesIO(file_content), header=None, nrows=MAX_EXCEL_ROWS)
            header_idx, cols = detect_header_and_columns(raw_df)
            if cols is None:
                return {
                    "status": "error",
                    "message": "Не удалось распознать колонки (нужны «Наименование» и «Кол-во»).",
                }

            name_i = cols["name"]
            qty_i, unit_i, note_i, link_i = cols["qty"], cols["unit"], cols["note"], cols["link"]
            article_i = cols["article"]
            data = raw_df.iloc[header_idx + 1 :]
            total_rows = len(data)

            for offset, (_, row) in enumerate(data.iterrows()):
                cells = list(row)
                raw_name = _cell(cells[name_i]) if name_i is not None and name_i < len(cells) else ""
                if not raw_name:
                    continue

                quantity = 1
                if qty_i is not None and qty_i < len(cells):
                    try:
                        quantity = max(1, int(float(_cell(cells[qty_i]))))
                    except (ValueError, TypeError):
                        pass

                unit = _cell(cells[unit_i]) if unit_i is not None and unit_i < len(cells) else ""
                note = _cell(cells[note_i]) if note_i is not None and note_i < len(cells) else ""
                article = _cell(cells[article_i]) if article_i is not None and article_i < len(cells) else ""
                link = _cell(cells[link_i]) if link_i is not None and link_i < len(cells) else ""
                if link and link not in note:
                    note = f"{note}\n{link}".strip()

                items_to_create.append(_build_quote_item(quote, raw_name, quantity, unit, note, mpn=article))

                if len(items_to_create) % 10 == 0 or (offset + 1) == total_rows:
                    self.update_state(state="PROGRESS", meta={"current": len(items_to_create), "total": total_rows})

        if not items_to_create:
            return {"status": "error", "message": "Файл обработан, но не найдено ни одной строки."}

        # Dedup/merge against existing lines AND within this batch — a re-imported
        # file (or two files sharing items) sums quantities instead of doubling rows.
        from crm.services.rfq import merge_request_lines

        with transaction.atomic():
            created, merged = merge_request_lines(quote, items_to_create)

        quote.recalculate_totals()
        logger.info("Excel import done: deal=%s user=%s created=%s merged=%s", deal_id, user_id, len(created), merged)
        return {"status": "success", "items_processed": len(created), "merged": merged}

    except Deal.DoesNotExist:
        return {"status": "error", "message": "Deal not found."}
    except (ValueError, KeyError, TypeError, OSError):
        logger.exception("Excel import failed: deal=%s user=%s", deal_id, user_id)
        return {"status": "error", "message": "Import failed. Please check the file format and try again."}


@shared_task(
    bind=True,
    time_limit=1800,
    soft_time_limit=1700,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_catalog_import(self, file_content_b64: str, supplier_company_id=None, dry_run=False):
    """
    Thin wrapper around the true-PIM seller catalog import engine (Rule 8).

    file_content_b64: base64-encoded XLSX (JSON-safe).
    supplier_company_id: the UPLOADER's seller company — its SupplierOffers are
        upserted. None ⇒ products-only (no offers).
    dry_run: validate + report counts without persisting (preview).
    """
    from .catalog_import import run_catalog_import

    def progress(current, total):
        self.update_state(state="PROGRESS", meta={"current": current, "total": total})

    try:
        file_content = base64.b64decode(file_content_b64)
        return run_catalog_import(
            file_content,
            supplier_company_id=supplier_company_id,
            dry_run=dry_run,
            progress_callback=progress,
        )
    except ValueError as exc:
        # File-level fatal error (e.g. NAME_COLUMN_NOT_FOUND).
        return {"status": "error", "message": str(exc)}
    except (KeyError, TypeError, OSError):
        logger.exception("Catalog import failed")
        return {"status": "error", "message": "Catalog import failed. Please check the file format and try again."}
