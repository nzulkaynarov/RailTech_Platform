"""Закрытие открытой проверки карточки (PART-2): публикация, снятие, архив и повторная отправка не оставляют её «висеть».

У карточки не больше одной открытой `ProductReview` (`catalog_one_pending_review`). Любое решение сотрудника по статусу
карточки обязано её закрыть: иначе следующая отправка партнёра упирается в ограничение базы. Очередь проверки (PART-3)
использует те же функции для решений «опубликована» и «возвращена».
"""

from __future__ import annotations

from django.utils import timezone

from .models import ProductReview


def close_pending_review(product, decision: str, actor=None, *, reason: str = "") -> int:
    """Закрыть открытую проверку карточки решением `decision`; сколько закрыто (0 — открытой не было)."""
    return ProductReview.objects.filter(product=product, decision=ProductReview.Decision.PENDING).update(
        decision=decision,
        decided_by=actor if getattr(actor, "pk", None) else None,
        decided_at=timezone.now(),
        reason=reason,
    )
