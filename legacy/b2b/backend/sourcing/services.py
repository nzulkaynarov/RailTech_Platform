import os
import re
from typing import List, Optional
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q, Case, When, Value, FloatField, F
from catalog.models import Product

# Threshold for Tier-3 fuzzy match. Configurable via env or SystemSetting.
DEFAULT_MATCH_THRESHOLD = float(os.environ.get('SMART_MATCH_THRESHOLD', '0.45'))


def _current_threshold() -> float:
    """Read threshold from SystemSetting if available; fall back to env default."""
    try:
        from core.models import SystemSetting
        val = SystemSetting.objects.filter(key='smart_match_threshold').values_list('value', flat=True).first()
        if val:
            return float(val)
    except Exception:
        pass
    return DEFAULT_MATCH_THRESHOLD


def normalize_string(text: str) -> str:
    """Standardizes strings for better matching (Upper, stripped, no double spaces)."""
    if not text:
        return ""
    text = text.upper().strip()
    return re.sub(r'\s+', ' ', text)


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
    qs = Product.objects.all().select_related('domain_type')
    if domain_hint:
        qs = qs.filter(domain_type__code=domain_hint)

    # 1. TIER 1: Exact matches (High Confidence)
    # Search by SKU or exact GOST/Drawing number
    exact_match = qs.filter(
        Q(sku__iexact=clean_name) |
        Q(gost_drawing__iexact=clean_name) |
        Q(name__iexact=clean_name)
    ).first()

    if exact_match:
        return exact_match

    # 2. TIER 2: Identifier extraction
    # If raw_name contains something that looks like a drawing number (e.g. "1234.56.789")
    # we try to find a product that has this drawing number in its field.
    potential_drawing = re.search(r'[0-9]{3,}[.0-9-]{3,}', clean_name)
    if potential_drawing:
        drawing_num = potential_drawing.group(0)
        drawing_match = qs.filter(gost_drawing__icontains=drawing_num).first()
        if drawing_match:
            return drawing_match

    # 3. TIER 3: Fuzzy Weighted Search
    # We combine name similarity with a 'bonus' if the GOST also matches partially
    threshold = _current_threshold()
    match = qs.annotate(
        name_sim=TrigramSimilarity('name', clean_name),
        gost_sim=TrigramSimilarity('gost_drawing', clean_name),
    ).annotate(
        # Weighted score: Name is important, but GOST is a strong signal
        total_score=Case(
            When(gost_sim__gt=0.5, then=F('name_sim') + Value(0.5)),
            default=F('name_sim'),
            output_field=FloatField()
        )
    ).filter(total_score__gt=threshold).order_by('-total_score').first()

    return match


def smart_match_candidates(raw_name: str, limit: int = 5, domain_hint: Optional[str] = None) -> List[dict]:
    """Return up to N candidate products with scores, for manual re-match UI.

    Returns list of dicts: [{product_id, sku, name, gost, score}]
    """
    if not raw_name:
        return []
    clean_name = normalize_string(raw_name)
    qs = Product.objects.all().select_related('domain_type')
    if domain_hint:
        qs = qs.filter(domain_type__code=domain_hint)

    scored = qs.annotate(
        name_sim=TrigramSimilarity('name', clean_name),
        gost_sim=TrigramSimilarity('gost_drawing', clean_name),
    ).annotate(
        total_score=Case(
            When(gost_sim__gt=0.5, then=F('name_sim') + Value(0.5)),
            default=F('name_sim'),
            output_field=FloatField()
        )
    ).filter(total_score__gt=0.15).order_by('-total_score')[:limit]

    return [
        {
            'product_id': p.id,
            'sku': p.sku,
            'name': p.name,
            'gost': p.gost_drawing,
            'score': round(float(getattr(p, 'total_score', 0) or 0), 3),
        }
        for p in scored
    ]
