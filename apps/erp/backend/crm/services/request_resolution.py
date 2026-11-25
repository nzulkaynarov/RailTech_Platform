"""РЕЗ-1: резолюция директора перед расчётом — настройка компании, а не зашитый шаг (owner 2026-11-25).

`CompanySettings.request_resolution` своей компании («Правила работы · Продажи»), два значения:

* `always` (по умолчанию) — письмо директору у каждой заявки, как раньше;
* `never` — резолюция не нужна: путь один для любого канала (сайт, бот, почта, письмо, телефон, Кабинет, ввод сотрудником).

Нужна ли резолюция, решает `required()`. Когда не нужна, `start_direct_calculation` ставит задание расчёта
ответственному (его же в обеих зонах виз), переводит сделку в «Расчёт», а в `request.created` уходит
`resolution_required=false` — EDS письма не заводит. Нет ответственного — заявка идёт прежним путём, не повисает.
Файл письма клиента (основание заявки) забирается из EDS после коммита задачей `integration.fetch_request_letter_file`;
пока его нет, расчёт показывает «файл заявки загружается» (`CalcTask.request_file_pending`).
Кто даёт резолюцию, здесь не задаётся: это держатели права EDS `letters.resolve` («Роли и права»).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.utils import timezone

MODES = ("always", "never")
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


def required() -> bool:
    """Нужна ли резолюция перед расчётом: настройка компании, одна для всех каналов (владелец 2026-11-25)."""
    return mode() != "never"


def start_direct_calculation(deal, crm_user_id: int, *, file_pending: bool = False):
    """Расчёт ответственному без резолюции: задание, обе зоны виз, стадия «Расчёт». Повтор — то же задание."""
    from . import calc_tasks

    return calc_tasks.apply_without_resolution(
        deal,
        crm_user_id=crm_user_id,
        due=timezone.localdate() + timedelta(days=DIRECT_DUE_DAYS),
        file_pending=file_pending,
    )


def active_crm_user(crm_user_id: Optional[int]) -> bool:
    """Сотрудник CRM подключён к ERP действующим пользователем — ему можно поставить расчёт."""
    from integration.models import CrmUserMapping

    return bool(crm_user_id) and CrmUserMapping.objects.filter(crm_user_id=crm_user_id, user__is_active=True).exists()


def responsible_crm_user_id(deal, manager_crm_user_id: Optional[int]) -> Optional[int]:
    """Ответственный за заявку — сотрудник CRM с действующим пользователем ERP: менеджер вызывающего, иначе
    ответственный сделки ERP. Без пользователя ERP считать некому — `None` (заявка идёт прежним путём, с письмом)."""
    from integration.services.event_builders import _crm_user_id

    found = (
        manager_crm_user_id
        or _crm_user_id(getattr(deal, "assigned_to", None))
        or _crm_user_id(getattr(deal, "manager", None))
    )
    return int(found) if active_crm_user(found) else None


def intake_info(user) -> dict:
    """Что будет с заявкой этого сотрудника: режим и может ли расчёт встать на него (иначе — письмо, с причиной)."""
    from integration.models import CrmUserMapping

    mapped = CrmUserMapping.objects.filter(user=user).exists()
    ready = active_crm_user(
        CrmUserMapping.objects.filter(user=user).values_list("crm_user_id", flat=True).first()
    ) and bool(getattr(user, "is_active", False))
    return {
        "mode": mode(),
        "ready": ready,
        "reason": None if ready else ("no_crm_mapping" if not mapped else "inactive"),
    }
