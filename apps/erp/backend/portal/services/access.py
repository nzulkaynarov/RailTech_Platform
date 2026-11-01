"""Кому открыт портал: компания «в обороте» и с типом CLIENT (FIX-15, K0).

Архив обязан снимать компанию со ВСЕХ поверхностей разом (см. `parties.models.core.active_company_q`), поэтому
вход, обмен ссылки, приглашение и проверка живой сессии спрашивают его здесь, а не читают `Company.is_active`.

K0 (решение владельца 2026-11-01): до волны K1 («кабинет контрагента») в кабинет входят только компании с типом CLIENT.
Поставщик, производитель и своя компания (она же поставщик) не входят, даже если у контакта есть e-mail или Telegram.
Правило одно — `company_has_cabinet_access` для одной компании и `cabinet_company_q` для выборок; мест, где оно
записано иначе, быть не должно.
"""

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from parties.models import Company, active_company_q

from accounts.constants import CompanyTypeCode
from core.tenant import own_company_id


def _own_company_id() -> int | None:
    """Id своей компании или `None` (её нет или определить нельзя: тогда решает тип, вход клиентов не ломаем)."""
    try:
        return own_company_id()
    except ImproperlyConfigured:
        return None


def cabinet_company_q(prefix: str = "") -> models.Q:
    """Предикат «компания допущена в кабинет»: в обороте, среди типов есть CLIENT, и это не своя компания.

    `prefix` — путь до Company от фильтруемой модели (`cabinet_company_q("company")` для Contact/PortalSession).
    Тип проверяется по одному коду, поэтому JOIN по M2M `types` не размножает строки.

    Своя компания (владелец ERP, `core.tenant`) исключена явно: сигнал `accounts.signals` выдаёт CLIENT каждой компании
    с типом SUPPLIER, так что одного типа для неё мало, а её контакты в кабинет клиента не входят.
    """
    field = f"{prefix}__types__code" if prefix else "types__code"
    q = active_company_q(prefix) & models.Q(**{field: CompanyTypeCode.CLIENT})
    own_id = _own_company_id()
    if own_id is not None:
        q &= ~models.Q(**{f"{prefix}__pk" if prefix else "pk": own_id})
    return q


def company_in_circulation(company_id: int | None) -> bool:
    """Компания существует и не в архиве."""
    if company_id is None:
        return False
    return Company.objects.filter(active_company_q(), pk=company_id).exists()


def company_has_cabinet_access(company_id: int | None) -> bool:
    """Компании открыт кабинет: не в архиве, тип CLIENT и не своя компания (K0)."""
    if company_id is None:
        return False
    return Company.objects.filter(cabinet_company_q(), pk=company_id).exists()
