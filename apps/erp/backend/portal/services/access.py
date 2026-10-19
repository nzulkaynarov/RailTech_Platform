"""Кому открыт портал: компания «в обороте» по общему предикату `active_company_q()` (FIX-15, хвост ревью FIX-14).

Архив обязан снимать компанию со ВСЕХ поверхностей разом (см. `parties.models.core.active_company_q`), поэтому
вход, обмен ссылки, приглашение и проверка живой сессии спрашивают его здесь, а не читают `Company.is_active`.
"""

from parties.models import Company, active_company_q


def company_in_circulation(company_id: int | None) -> bool:
    """Компания существует и не в архиве."""
    if company_id is None:
        return False
    return Company.objects.filter(active_company_q(), pk=company_id).exists()
