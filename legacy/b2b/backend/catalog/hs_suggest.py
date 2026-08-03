"""Подсказка кода ТН ВЭД по наименованию товара — ВЫБОР из справочника, а не сочинение.

Ключевая мысль: придуманный код ТН ВЭД хуже отсутствующего. Десять цифр выглядят одинаково
убедительно и когда они верные, и когда выдуманы, а узнает продавец об ошибке на границе.
Поэтому подсказка работает ТОЛЬКО поверх наполненного классификатора (`master_data.HSCode`):
кандидаты выбираются из закрытого списка, и у каждого есть код-первоисточник.

Порядок такой же, как у подбора товара: сначала точное совпадение кода, затем поиск по
наименованию позиции. Языковая модель сюда не входит — это детерминированный retrieval; когда
справочник наполнится, она сможет ВЫБИРАТЬ из этих кандидатов (RAG), но не генерировать цифры.

Справочник пуст — возвращаем пусто и молчим: система обязана работать без него, код тогда
вводится вручную, как сегодня.
"""

from __future__ import annotations

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q


def suggest_hs_codes(text: str, limit: int = 5, min_level: int = 6) -> list[dict]:
    """Кандидаты `[{code, name, level, score}]` по наименованию товара.

    `min_level` отсекает слишком общие ветки: группа «84 — Реакторы ядерные, котлы,
    оборудование» в карточке бесполезна, продавцу нужен рабочий уровень субпозиции и ниже.
    """
    from master_data.models import HSCode

    query = (text or "").strip()
    if not query:
        return []

    rows = HSCode.objects.filter(level__gte=min_level)
    # Пользователь мог ввести сам код — тогда это точный поиск, а не текстовый.
    digits = "".join(ch for ch in query if ch.isdigit())
    if len(digits) >= 4:
        exact = list(
            HSCode.objects.filter(Q(code=digits) | Q(code__startswith=digits))
            .order_by("code")[:limit]
            .values("code", "name", "level")
        )
        if exact:
            return [dict(row, score=1.0) for row in exact]

    scored = (
        rows.annotate(score=TrigramSimilarity("name", query))
        .filter(score__gt=0.15)
        .order_by("-score", "code")[:limit]
        .values("code", "name", "level", "score")
    )
    return [dict(row, score=round(float(row["score"]), 3)) for row in scored]


def is_known_code(code: str) -> bool:
    """Есть ли код в справочнике. Пустой справочник → True: не блокируем работу без данных."""
    from master_data.models import HSCode

    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if not digits:
        return False
    if not HSCode.objects.exists():
        return True
    return HSCode.objects.filter(code=digits).exists()
