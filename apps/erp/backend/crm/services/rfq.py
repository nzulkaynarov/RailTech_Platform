"""Строки заявки: слияние дубликатов при импорте (FIX-13).

Покупательского пути «заявка → отправка» в ERP больше нет: клиент оформляет запрос в портале
(`/api/portal/v1/*`), сотрудник собирает КП сам. Остался только общий для импорта Excel и ИИ-разбора
помощник — слияние одинаковых строк по артикулу / ГОСТ / имени.
"""

from ..models import Quote, QuoteItem


def _line_dedup_key(item: QuoteItem):
    """Identity of a request line for dedup: prefer code (mpn / ГОСТ-чертёж), else name+unit."""
    mpn = (item.mpn or "").strip().lower()
    if mpn:
        return ("mpn", mpn)
    gost = (item.gost_drawing or "").strip().lower()
    if gost:
        return ("gost", gost)
    name = (item.imported_raw_name or (item.product.name if item.product_id and item.product else "")).strip().lower()
    return ("name", name, (item.unit or "").strip().lower())


def merge_request_lines(quote: Quote, new_items: list) -> tuple:
    """Add unsaved QuoteItem rows to `quote`, deduping by mpn / ГОСТ / (name+unit)
    against existing lines AND within the batch — same item ⇒ quantities sum.
    Idempotent for re-imports. Returns (created_list, merged_count)."""
    existing = {}
    for line in quote.items.all():
        existing[_line_dedup_key(line)] = line
    created, touched, merged = [], [], 0
    for incoming in new_items:
        key = _line_dedup_key(incoming)
        if key in existing:
            existing[key].quantity += incoming.quantity
            if existing[key].pk:
                touched.append(existing[key])
            merged += 1
        else:
            existing[key] = incoming
            created.append(incoming)
    if created:
        QuoteItem.objects.bulk_create(created)
    for line in touched:
        line.version = (line.version or 0) + 1  # количество изменилось — версия строки растёт (D2-1)
        line.save(update_fields=["quantity", "version"])
    return created, merged
