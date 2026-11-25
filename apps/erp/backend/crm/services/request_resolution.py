"""РЕЗ-1: резолюция директора перед расчётом — настройка компании, а не зашитый шаг (owner 2026-11-25).

`CompanySettings.request_resolution` своей компании («Правила работы · Продажи»):

* `always` (по умолчанию) — письмо директору у каждой заявки, как раньше;
* `cabinet_letters` — письмо только у заявок из Кабинета (письма регистрирует сам EDS и от этой настройки не зависят);
  заявка, заведённая сотрудником или переданная из CRM, идёт сразу в расчёт;
* `never` — резолюция не нужна нигде.

Нужна ли резолюция, решает `required(source)`. Когда не нужна, `start_direct_calculation` ставит задание расчёта
ответственному (его же в обеих зонах виз), переводит сделку в «Расчёт», а в `request.created` уходит
`resolution_required=false` — EDS письма не заводит. Нет ответственного — заявка идёт прежним путём, не повисает.
Кто даёт резолюцию, здесь не задаётся: это держатели права EDS `letters.resolve` («Роли и права»).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.utils import timezone

MODES = ("always", "cabinet_letters", "never")
DEFAULT_MODE = "always"
#: Срок расчёта без резолюции: резолюция задавала его вручную; здесь — календарные дни от заведения заявки.
DIRECT_DUE_DAYS = 3


def mode() -> str:
    from parties.models.company_settings import CompanySettings

    from core.tenant import own_company_id

    company_id = own_company_id()
    if company_id is None:
        return DEFAULT_MODE
    value = CompanySettings.objects.filter(company_id=company_id).values_list("request_resolution", flat=True).first()
    return value if value in MODES else DEFAULT_MODE


def required(source: str) -> bool:
    """Нужна ли резолюция по заявке из источника `source` (`crm` | `cabinet` | `erp`)."""
    current = mode()
    if current == "never":
        return False
    if current == "cabinet_letters":
        return source == "cabinet"
    return True


def start_direct_calculation(deal, crm_user_id: int):
    """Расчёт ответственному без резолюции: задание, обе зоны виз, стадия «Расчёт». Повтор — то же задание."""
    from . import calc_tasks

    return calc_tasks.apply_without_resolution(
        deal, crm_user_id=crm_user_id, due=timezone.localdate() + timedelta(days=DIRECT_DUE_DAYS)
    )


def responsible_crm_user_id(deal, manager_crm_user_id: Optional[int]) -> Optional[int]:
    """Ответственный за заявку — сотрудник CRM: менеджер вызывающего, иначе ответственный сделки ERP."""
    from integration.services.event_builders import _crm_user_id

    if manager_crm_user_id:
        return int(manager_crm_user_id)
    found = _crm_user_id(getattr(deal, "assigned_to", None)) or _crm_user_id(getattr(deal, "manager", None))
    return int(found) if found else None
