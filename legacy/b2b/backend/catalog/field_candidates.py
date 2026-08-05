"""Кандидаты справочных полей карточки для ИИ-предложений: категория и единица измерения.

Тот же приём, которым в проекте уже закрыт код ТН ВЭД (`catalog/hs_suggest.py`): модель не
ГЕНЕРИРУЕТ значение справочного поля, а ВЫБИРАЕТ из закрытого списка, который мы же собрали
из базы до вызова (retrieval → выбор → детерминированная сверка). Придуманный id категории —
это молчаливая порча мастер-данных (карточка уедет не в ту ветку каталога и не найдётся
поиском), придуманный код единицы — арифметика КП не в тех единицах.

Эталон — Akeneo AI suggestions / Shopify Magic: система предлагает ЗНАЧЕНИЕ ИЗ СВОЕГО
справочника по каждому полю, человек принимает или отклоняет.

Справочник пуст — возвращаем пустой список и молчим: блок в промпт не уходит, поле остаётся
пустым, работа продавца не блокируется (то же правило, что у ТН ВЭД).
"""

from __future__ import annotations

import re

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Q
from django.db.models.functions import Greatest

# Размер списка категорий. Стартовая таксономия (миграция catalog/0015) даёт максимум 10
# категорий на домен, поэтому 15 — это ВЕСЬ домен целиком плюс запас на расширения оператора
# и на категории без домена. Верхняя граница нужна лишь как предохранитель от разросшегося
# дерева: список длиннее десятка перестаёт быть выбором и начинает быть шумом (Akeneo
# показывает человеку примерно столько же вариантов).
CATEGORY_CANDIDATE_LIMIT = 15

# Единиц измерения в справочнике 17 (UN/ECE Rec 20, миграция master_data/0005) — весь список
# помещается в промпт целиком, и это принципиально: обрезанный список молча делает правильную
# единицу невыбираемой. 24 — тот же список с запасом на добавления оператора; предохранитель
# сработает, только если кто-то зальёт весь классификатор UN/ECE (~300 кодов).
UOM_CANDIDATE_LIMIT = 24


def _full_name(category) -> str:
    """Имя категории с родителем: в дереве «Инструмент» под разными ветками — разные вещи."""
    parent = getattr(category, "parent", None)
    return f"{parent.name} / {category.name}" if parent else category.name


def category_candidates(text: str, domain_code: str | None = None, limit: int = CATEGORY_CANDIDATE_LIMIT) -> list[dict]:
    """Кандидаты категории `[{id, name}]` для наименования товара.

    Фильтр по домену, когда домен известен: категории чужого домена в карточке бессмысленны.
    Категории БЕЗ домена остаются в списке — доменом они не ограничены и годятся любому товару
    (`Product.category` доменом не связана), а пропущенный правильный кандидат невосполним:
    модель из ничего выбрать не может.

    Порядок — по сходству имени с наименованием товара (пословно, как в подсказке ТН ВЭД:
    словарь каталога ≠ словарь продавца), затем таксономический. Порог сходства НЕ ставится:
    список короткий и закрытый, лишний кандидат в хвосте безвреден — модель обязана вернуть
    «ничего не подходит», а сверка всё равно отвергнет всё, чего в списке не было.
    """
    from catalog.models import Category

    rows = Category.objects.filter(is_active=True).select_related("parent")
    if domain_code:
        rows = rows.filter(Q(domain_type__code=domain_code) | Q(domain_type__isnull=True))

    query = (text or "").strip()
    if query:
        words = [word for word in re.split(r"[^\wА-Яа-яЁё]+", query) if len(word) >= 4][:5]
        similarities = [TrigramWordSimilarity(query, "name")] + [TrigramWordSimilarity(word, "name") for word in words]
        score = similarities[0] if len(similarities) == 1 else Greatest(*similarities)
        rows = rows.annotate(match_score=score).order_by("-match_score", "sort_order", "name")
    else:
        rows = rows.order_by("sort_order", "name")

    return [{"id": row.pk, "name": _full_name(row)} for row in rows[:limit]]


def uom_candidates(limit: int = UOM_CANDIDATE_LIMIT) -> list[dict]:
    """Активные единицы измерения `[{code, name}]` в порядке справочника.

    Список отдаётся целиком (он короткий) — ранжировать нечего: выбор единицы делается по
    смыслу товара, а не по сходству строк.
    """
    from master_data.models import UnitOfMeasure

    rows = UnitOfMeasure.objects.filter(is_active=True).order_by("sort_order", "name")
    return list(rows[:limit].values("code", "name"))
