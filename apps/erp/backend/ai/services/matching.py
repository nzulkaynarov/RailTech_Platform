"""Сопоставление строк запроса с каталогом (feature `match`/`canonicalize`, алиас `match-model`).

Дешёвый SQL-префильтр (триграммы + точный ГОСТ/чертёж) сужает каталог до шорт-листа на
строку; модель только РАНЖИРУЕТ шорт-лист. `product_id` принимается, только если он был среди
кандидатов этой строки (Rule 1: id никогда не приходит от модели). Многоязычное ранжирование
(рус/узб/англ) — ради этого и нужна модель: свободный текст запроса ↔ иначе названная позиция.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from .gateway import JsonCall, call_json, text_block
from .prompts import load_prompt

logger = logging.getLogger(__name__)

MATCH_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_index": {"type": "integer"},
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "confidence": {"type": "number", "description": "0..1"},
                                "reason": {"type": "string"},
                            },
                            "required": ["product_id", "confidence", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["line_index", "candidates"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}

CANONICALIZE_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "name_canonical": {"type": "string"}},
                "required": ["index", "name_canonical"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Candidate:
    """Позиция каталога, которую видит модель (только то, что нужно для ранжирования)."""

    product_id: int
    name: str
    sku: str = ""
    gost_drawing: str = ""


def _ai_on() -> bool:
    return bool(getattr(settings, "AI_IMPORT_ENABLED", False))


def canonicalize_names(names: list[str]) -> dict[str, str]:
    """Латиница/опечатки → канонические русские наименования, одним вызовом.

    {исходное: каноническое} только для изменившихся имён; {} при выключенном ИИ или ошибке —
    вызывающий всегда деградирует к детерминированному пути.
    """
    unique = list(dict.fromkeys(name.strip() for name in names if (name or "").strip()))
    if not _ai_on() or not unique:
        return {}
    prompt = load_prompt("canonicalize")
    listing = "\n".join(f"{index}: {name}" for index, name in enumerate(unique))
    result = call_json(
        JsonCall(
            feature="canonicalize",
            prompt=prompt,
            system=prompt.render(),
            user_content=[text_block(listing)],
            schema=CANONICALIZE_RESULT_SCHEMA,
            max_tokens=1500,
        )
    )
    if not result.ok:
        return {}
    canonical_by_name: dict[str, str] = {}
    for item in result.data.get("items", []):
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(unique):
            continue  # the model must address a line we actually sent
        canonical = (item.get("name_canonical") or "").strip()[:500]
        if canonical and canonical.casefold() != unique[index].casefold():
            canonical_by_name[unique[index]] = canonical
    return canonical_by_name


def shortlist_products(line: dict, domain_code: str | None, limit: int = 8):
    """Триграммы + точный ГОСТ/чертёж: шорт-лист ОПУБЛИКОВАННЫХ карточек для одной строки.

    Сырое `name` и каноническое `name_canonical` оба идут в сходство, берётся наибольшее — так
    латинский запрос находит кириллическую карточку."""
    from django.contrib.postgres.search import TrigramSimilarity
    from django.db.models.functions import Greatest

    from catalog.models import Product

    qs = Product.objects.filter(status__code="PUBLISHED")
    if domain_code:
        qs = qs.filter(domain_type__code=domain_code)
    found: dict[int, object] = {}
    gost = (line.get("gost_drawing") or "").strip()
    if gost:
        for product in qs.filter(gost_drawing__iexact=gost)[:limit]:
            found[product.id] = product
    name = (line.get("name") or "").strip()
    name_canonical = (line.get("name_canonical") or "").strip()
    terms = [term for term in dict.fromkeys([name, name_canonical]) if term]
    if terms and len(found) < limit:
        similarities = [TrigramSimilarity("name", term) for term in terms]
        similarity = similarities[0] if len(similarities) == 1 else Greatest(*similarities)
        ranked = qs.annotate(similarity=similarity).filter(similarity__gt=0.1).order_by("-similarity")[:limit]
        for product in ranked:
            found.setdefault(product.id, product)
    return list(found.values())[:limit]


def _line_label(line: dict) -> str:
    label = (line.get("name") or "").strip()
    canonical = (line.get("name_canonical") or "").strip()
    if canonical and canonical.casefold() != label.casefold():
        label += f" | рус. {canonical}"
    if line.get("mpn"):
        label += f" | артикул {line['mpn']}"
    if line.get("gost_drawing"):
        label += f" | ГОСТ {line['gost_drawing']}"
    return label or "(без названия)"


def _candidate_label(candidate: Candidate) -> str:
    label = f"[id={candidate.product_id}] {candidate.name}"
    if candidate.gost_drawing:
        label += f" (ГОСТ {candidate.gost_drawing})"
    if candidate.sku:
        label += f" [SKU {candidate.sku}]"
    return label


def _valid_candidates(match: dict, pool: dict[int, Candidate], top_k: int) -> list[dict]:
    valid = []
    for raw in match.get("candidates", []):
        candidate = pool.get(raw.get("product_id"))
        if candidate is None:  # Rule 1: id must be from the DB shortlist
            continue
        try:
            confidence = round(float(raw.get("confidence") or 0), 3)
        except (TypeError, ValueError):
            confidence = 0.0
        valid.append(
            {
                "product_id": candidate.product_id,
                "name": candidate.name,
                "sku": candidate.sku,
                "confidence": confidence,
                "reason": (raw.get("reason") or "")[:300],
            }
        )
    valid.sort(key=lambda row: -row["confidence"])
    return valid[:top_k]


def rank_candidates(lines: list[dict], shortlists: dict[int, list[Candidate]], top_k: int = 3) -> list[dict]:
    """Ранжирование моделью готовых шорт-листов (без БД — его же гоняют evals).

    Возвращает `[{line_index, name_canonical, candidates: [...]}]` только для строк, где остался
    хотя бы один кандидат из ЕЁ шорт-листа."""
    blocks = [
        f"Строка {index}: {_line_label(lines[index])}\n  Кандидаты: " + "; ".join(map(_candidate_label, pool))
        for index, pool in sorted(shortlists.items())
        if pool and 0 <= index < len(lines)
    ]
    if not _ai_on() or not blocks:
        return []
    prompt = load_prompt("match")
    result = call_json(
        JsonCall(
            feature="match",
            prompt=prompt,
            system=prompt.render(),
            user_content=[text_block("Сопоставь строки заявки с кандидатами каталога:\n\n" + "\n\n".join(blocks))],
            schema=MATCH_RESULT_SCHEMA,
            max_tokens=3000,
        )
    )
    if not result.ok:
        return []
    pools = {index: {c.product_id: c for c in pool} for index, pool in shortlists.items()}
    ranked = []
    for match in result.data.get("matches", []):
        index = match.get("line_index")
        valid = _valid_candidates(match, pools.get(index) or {}, top_k) if isinstance(index, int) else []
        if valid:
            name_canonical = (lines[index].get("name_canonical") or "").strip() if 0 <= index < len(lines) else ""
            ranked.append({"line_index": index, "name_canonical": name_canonical, "candidates": valid})
    return ranked


def match_lines_to_catalog(lines: list[dict], domain_code: str | None = None, top_k: int = 3) -> list[dict]:
    """Каждая строка запроса → до `top_k` кандидатов каталога (шорт-лист из БД + ранжирование).

    [] при выключенном ИИ. Человек подтверждает кандидата в сетке (никакой молчаливой привязки,
    кроме уверенной привязки в черновик КП — `crm.services.draft_quote`)."""
    if not _ai_on() or not lines:
        return []
    shortlists: dict[int, list[Candidate]] = {}
    for index, line in enumerate(lines):
        products = shortlist_products(line, domain_code)
        if products:
            shortlists[index] = [
                Candidate(
                    product_id=product.id,
                    name=product.name,
                    sku=getattr(product, "sku", "") or "",
                    gost_drawing=getattr(product, "gost_drawing", "") or "",
                )
                for product in products
            ]
    return rank_candidates(lines, shortlists, top_k=top_k)
