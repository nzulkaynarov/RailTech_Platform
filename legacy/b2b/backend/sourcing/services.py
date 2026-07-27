import logging
import os
import re
from typing import List, Optional

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Case, F, FloatField, Q, Value, When

from catalog.models import Product

logger = logging.getLogger(__name__)

# Threshold for Tier-3 fuzzy match. Configurable via env or SystemSetting.
DEFAULT_MATCH_THRESHOLD = float(os.environ.get("SMART_MATCH_THRESHOLD", "0.45"))


def _current_threshold() -> float:
    """Tier-3 fuzzy-match threshold. Configurable via the SMART_MATCH_THRESHOLD
    env var (SystemSetting has no per-key store — it's a fixed-field singleton)."""
    return DEFAULT_MATCH_THRESHOLD


def normalize_string(text: str) -> str:
    """Standardizes strings for better matching (Upper, stripped, no double spaces)."""
    if not text:
        return ""
    text = text.upper().strip()
    return re.sub(r"\s+", " ", text)


def smart_match_product(raw_name: str, domain_hint: Optional[str] = None) -> Optional[Product]:
    """
    Advanced Product Matching Engine.
    Strategy:
    1. Exact identifiers (SKU, GOST/Drawing) - Highest priority.
    2. Fuzzy match on name with GOST reinforcement.
    """
    if not raw_name:
        return None

    clean_name = normalize_string(raw_name)

    # Base queryset
    qs = Product.objects.all().select_related("domain_type")
    if domain_hint:
        qs = qs.filter(domain_type__code=domain_hint)

    # 1. TIER 1: Exact matches (High Confidence)
    # Search by SKU or exact GOST/Drawing number
    exact_match = qs.filter(
        Q(sku__iexact=clean_name) | Q(gost_drawing__iexact=clean_name) | Q(name__iexact=clean_name)
    ).first()

    if exact_match:
        return exact_match

    # 2. TIER 2: Identifier extraction
    # If raw_name contains something that looks like a drawing number (e.g. "1234.56.789")
    # we try to find a product that has this drawing number in its field.
    potential_drawing = re.search(r"[0-9]{3,}[.0-9-]{3,}", clean_name)
    if potential_drawing:
        drawing_num = potential_drawing.group(0)
        drawing_match = qs.filter(gost_drawing__icontains=drawing_num).first()
        if drawing_match:
            return drawing_match

    # 3. TIER 3: Fuzzy Weighted Search
    # We combine name similarity with a 'bonus' if the GOST also matches partially
    threshold = _current_threshold()
    match = (
        qs.annotate(
            name_sim=TrigramSimilarity("name", clean_name),
            gost_sim=TrigramSimilarity("gost_drawing", clean_name),
        )
        .annotate(
            # Weighted score: Name is important, but GOST is a strong signal
            total_score=Case(
                When(gost_sim__gt=0.5, then=F("name_sim") + Value(0.5)),
                default=F("name_sim"),
                output_field=FloatField(),
            )
        )
        .filter(total_score__gt=threshold)
        .order_by("-total_score")
        .first()
    )

    return match


def smart_match_candidates(raw_name: str, limit: int = 5, domain_hint: Optional[str] = None) -> List[dict]:
    """Return up to N candidate products with scores, for manual re-match UI.

    Returns list of dicts: [{product_id, sku, name, gost, score}]
    """
    if not raw_name:
        return []
    clean_name = normalize_string(raw_name)
    qs = Product.objects.all().select_related("domain_type")
    if domain_hint:
        qs = qs.filter(domain_type__code=domain_hint)

    scored = (
        qs.annotate(
            name_sim=TrigramSimilarity("name", clean_name),
            gost_sim=TrigramSimilarity("gost_drawing", clean_name),
        )
        .annotate(
            total_score=Case(
                When(gost_sim__gt=0.5, then=F("name_sim") + Value(0.5)),
                default=F("name_sim"),
                output_field=FloatField(),
            )
        )
        .filter(total_score__gt=0.15)
        .order_by("-total_score")[:limit]
    )

    return [
        {
            "product_id": p.id,
            "sku": p.sku,
            "name": p.name,
            "gost": p.gost_drawing,
            "score": round(float(getattr(p, "total_score", 0) or 0), 3),
        }
        for p in scored
    ]


def suggest_sellers_for_deal(deal, *, per_line_candidates: int = 3) -> List[dict]:
    """R1 (spec-freetext-rfq-routing): подобрать продавцов для заявки по её позициям.

    Паттерн category-matched routing (Ariba Discovery / Alibaba RFQ). Каждая позиция заявки →
    каталожный товар (СВОЙ product_id, если позиция взята из каталога, ИЛИ trigram-матч free-text
    имени к PUBLISHED-товарам) → `owner_company` (продавец). Агрегируем по компании со счётом
    СОВПАВШИХ позиций — наш аналог confidence («совпало 3 из 5»). Только SUPPLIER-компании.
    Чистое чтение: ничего не пишет, никакого AI — детерминированный trigram.

    Возврат по убыванию совпадений: [{company_id, name, matched_lines, total_lines}].
    Пустой список, когда каталог ничего не подсказал (UI оставляет ручной выбор — без тупика).
    """
    from collections import defaultdict

    from accounts.constants import SELLER_COMPANY_TYPES
    from accounts.models import Company

    request_quote = deal.quotes.filter(prepared_by__isnull=True).order_by("version").first()
    if request_quote is None:
        return []
    lines = [
        item
        for item in request_quote.items.all()
        if item.product_id or (item.imported_raw_name or "").strip()
    ]
    if not lines:
        return []

    company_hits: dict = defaultdict(int)  # seller company id → сколько позиций она может закрыть
    for line in lines:
        if line.product_id:
            product_ids = [line.product_id]
        else:
            product_ids = [c["product_id"] for c in smart_match_candidates(line.imported_raw_name, limit=per_line_candidates)]
        if not product_ids:
            continue
        owner_ids = (
            Product.objects.filter(
                id__in=product_ids,
                status__code="PUBLISHED",
                owner_company__types__code__in=SELLER_COMPANY_TYPES,
            )
            .values_list("owner_company_id", flat=True)
            .distinct()
        )
        for owner_id in owner_ids:
            if owner_id:
                company_hits[owner_id] += 1  # одна позиция засчитывается компании один раз

    if not company_hits:
        return []
    names = dict(Company.objects.filter(id__in=list(company_hits)).values_list("id", "name"))
    total_lines = len(lines)
    result = [
        {"company_id": cid, "name": names.get(cid, ""), "matched_lines": hits, "total_lines": total_lines}
        for cid, hits in company_hits.items()
    ]
    result.sort(key=lambda row: (-row["matched_lines"], row["name"]))
    return result
