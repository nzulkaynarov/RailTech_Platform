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


def _request_lines_for_routing(deal):
    """The buyer-request КП lines usable for routing (a catalog product OR a non-empty free-text
    name). Empty when the deal has no buyer request or no usable lines."""
    request_quote = deal.quotes.filter(prepared_by__isnull=True).order_by("version").first()
    if request_quote is None:
        return []
    return [item for item in request_quote.items.all() if item.product_id or (item.imported_raw_name or "").strip()]


def _owner_ids_for_products(product_ids) -> set:
    """PUBLISHED seller owner-company ids for the given products — only sellers a buyer can
    actually invite.

    The KYC filter is load-bearing, not defensive: the recipient picker lists only verified
    sellers, while the suggestion pre-checks the companies it returns. Suggesting an unverified
    seller therefore pre-selected a company that had NO row in the picker — invisible to the
    buyer, impossible to un-check, and still sent to routing. Same set as the picker
    (accounts/views/company.py `suppliers`), so suggestion ⊆ picker by construction.
    """
    if not product_ids:
        return set()
    from accounts.constants import SELLER_COMPANY_TYPES
    from accounts.services.kyc import KYC_VERIFIED_CODES

    owner_ids = (
        Product.objects.filter(
            id__in=product_ids,
            status__code="PUBLISHED",
            owner_company__types__code__in=SELLER_COMPANY_TYPES,
            owner_company__verification_status__code__in=KYC_VERIFIED_CODES,
        )
        .values_list("owner_company_id", flat=True)
        .distinct()
    )
    return {owner_id for owner_id in owner_ids if owner_id}


def _trigram_owner_ids_for_line(line, per_line_candidates: int) -> set:
    """Deterministic per-line owner set: the line's own product owner, or trigram-matched
    catalog owners for a free-text line. No AI, no writes."""
    if line.product_id:
        return _owner_ids_for_products([line.product_id])
    product_ids = [c["product_id"] for c in smart_match_candidates(line.imported_raw_name, limit=per_line_candidates)]
    return _owner_ids_for_products(product_ids)


def _build_seller_suggestions(company_hits: dict, total_lines: int) -> List[dict]:
    """Shape + sort the aggregated hits into the API result [{company_id, name, matched_lines,
    total_lines}], most-matched first (name tiebreak)."""
    if not company_hits:
        return []
    from accounts.models import Company

    names = dict(Company.objects.filter(id__in=list(company_hits)).values_list("id", "name"))
    result = [
        {"company_id": cid, "name": names.get(cid, ""), "matched_lines": hits, "total_lines": total_lines}
        for cid, hits in company_hits.items()
    ]
    result.sort(key=lambda row: (-row["matched_lines"], row["name"]))
    return result


def suggest_sellers_for_deal(deal, *, per_line_candidates: int = 3) -> List[dict]:
    """R1 (spec-freetext-rfq-routing): подобрать продавцов для заявки по её позициям.

    Паттерн category-matched routing (Ariba Discovery / Alibaba RFQ). Каждая позиция заявки →
    каталожный товар (СВОЙ product_id, если позиция взята из каталога, ИЛИ trigram-матч free-text
    имени к PUBLISHED-товарам) → `owner_company` (продавец). Агрегируем по компании со счётом
    СОВПАВШИХ позиций — наш аналог confidence («совпало 3 из 5»). Только SUPPLIER-компании.
    Чистое чтение: ничего не пишет, никакого AI — детерминированный trigram (мгновенно).

    Возврат по убыванию совпадений: [{company_id, name, matched_lines, total_lines}].
    Пустой список, когда каталог ничего не подсказал (UI оставляет ручной выбор — без тупика).
    """
    from collections import defaultdict

    lines = _request_lines_for_routing(deal)
    if not lines:
        return []
    company_hits: dict = defaultdict(int)
    for line in lines:
        for owner_id in _trigram_owner_ids_for_line(line, per_line_candidates):
            company_hits[owner_id] += 1  # одна позиция засчитывается компании один раз
    return _build_seller_suggestions(company_hits, len(lines))


def _canonicalize_missing_names(ai_candidate_lines: list[dict]) -> None:
    """Заполнить пустой `name_canonical` у строк, набранных руками (мутирует список).

    Без этого шага AI-ветка бесполезна ровно там, где заявлена. `match_lines_to_catalog`
    сначала строит шорт-лист товаров ТРИГРАМОМ (по `name` и `name_canonical`), и у латиницы
    вроде «relsy R65» сходство с кириллической карточкой ≈ 0 → шорт-лист пуст → модель даже
    не вызывается. У строк из файлового ИИ-импорта `name_canonical` уже есть, у набранных
    руками — нет. Один батчевый вызов канонизации закрывает этот разрыв.
    """
    from sourcing.services_ai import canonicalize_names

    needs_canonical = [line["name"] for line in ai_candidate_lines if not line["name_canonical"]]
    if not needs_canonical:
        return
    canonical_by_name = canonicalize_names(needs_canonical)
    for line in ai_candidate_lines:
        if not line["name_canonical"]:
            line["name_canonical"] = canonical_by_name.get(line["name"], "")


def suggest_sellers_for_deal_ai(deal, *, per_line_candidates: int = 3) -> List[dict]:
    """R3 — то же, что `suggest_sellers_for_deal`, но free-text позиции БЕЗ trigram-совпадения
    добираются ИИ: сначала батчевая канонизация имён (латиница/опечатки → русское каноническое),
    затем `match_lines_to_catalog` (шорт-лист + LLM-реранк). Ловит то, что триграм пропускает.

    Опциональное усиление (покупатель запускает явно, под суточным лимитом ИИ); человек всё
    равно подтверждает список — AI ничего не привязывает сам. Деградирует до детерминированного
    результата, когда AI выключен или не дал кандидатов. Тот же shape, что у R1."""
    from collections import defaultdict

    from sourcing.services_ai import match_lines_to_catalog

    lines = _request_lines_for_routing(deal)
    if not lines:
        return []

    company_hits: dict = defaultdict(int)
    ai_candidate_lines: list[dict] = []  # free-text misses to send to the model in one batch
    for line in lines:
        owner_ids = _trigram_owner_ids_for_line(line, per_line_candidates)
        if owner_ids:
            for owner_id in owner_ids:
                company_hits[owner_id] += 1
        elif (line.imported_raw_name or "").strip():
            ai_candidate_lines.append(
                {
                    "name": line.imported_raw_name or "",
                    "name_canonical": getattr(line, "name_canonical", "") or "",
                    "mpn": getattr(line, "mpn", "") or "",
                    "gost_drawing": getattr(line, "gost_drawing", "") or "",
                }
            )

    if ai_candidate_lines:
        _canonicalize_missing_names(ai_candidate_lines)
        for match in match_lines_to_catalog(ai_candidate_lines, top_k=per_line_candidates):
            product_ids = [c["product_id"] for c in match.get("candidates", []) if c.get("product_id")]
            for owner_id in _owner_ids_for_products(product_ids):
                company_hits[owner_id] += 1  # одна (AI-распознанная) позиция — один зачёт компании

    return _build_seller_suggestions(company_hits, len(lines))
