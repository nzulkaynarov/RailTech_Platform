"""РЕЗ-1: резолюция директора перед расчётом — настройка компании, а не зашитый шаг (owner 2026-11-25).

`CompanySettings.request_resolution` своей компании («Правила работы · Продажи»):

* `always` (по умолчанию) — письмо директору у каждой заявки, как раньше;
* `client_own` — «только заявки, которые клиент подал сам»: Кабинет, бот и заявка по письму клиента; заявка, заведённая
  сотрудником, идёт сразу в расчёт;
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

MODES = ("always", "client_own", "never")
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


def required(source: str, *, client_initiated: bool = False) -> bool:
    """Нужна ли резолюция по заявке из источника `source` (`crm` | `cabinet` | `erp`).

    `client_initiated` — заявку подал сам клиент (бот, передача из лида, заявка по его письму); Кабинет — всегда."""
    current = mode()
    if current == "never":
        return False
    if current == "client_own":
        return source == "cabinet" or client_initiated
    return True


def start_direct_calculation(deal, crm_user_id: int):
    """Расчёт ответственному без резолюции: задание, обе зоны виз, стадия «Расчёт». Повтор — то же задание."""
    from . import calc_tasks

    return calc_tasks.apply_without_resolution(
        deal, crm_user_id=crm_user_id, due=timezone.localdate() + timedelta(days=DIRECT_DUE_DAYS)
    )


def responsible_crm_user_id(deal, manager_crm_user_id: Optional[int]) -> Optional[int]:
    """Ответственный за заявку — сотрудник CRM с действующим пользователем ERP: менеджер вызывающего, иначе
    ответственный сделки ERP. Без пользователя ERP считать некому — `None` (заявка идёт прежним путём, с письмом)."""
    from integration.models import CrmUserMapping
    from integration.services.event_builders import _crm_user_id

    found = (
        manager_crm_user_id
        or _crm_user_id(getattr(deal, "assigned_to", None))
        or _crm_user_id(getattr(deal, "manager", None))
    )
    if not found:
        return None
    active = CrmUserMapping.objects.filter(crm_user_id=found, user__is_active=True).exists()
    return int(found) if active else None


def fetch_letter_file(file_id: str, created_by: Optional[int]):
    """Файл письма клиента из EDS (сервисный путь, только непривязанный файл автора заявки): `(имя, байты)` или `None`."""
    import httpx
    from django.conf import settings

    token = settings.SERVICE_TOKEN_ERP_TO_EDS
    if not token or not created_by:
        return None
    try:
        response = httpx.get(
            f"{settings.EDS_INTERNAL_URL}/api/v1/service/files/{file_id}",
            params={"created_by": int(created_by)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    from urllib.parse import unquote

    disposition = response.headers.get("content-disposition", "")
    name = unquote(disposition.split("filename*=UTF-8''", 1)[1]) if "filename*=UTF-8''" in disposition else "letter"
    return name[:255], response.content


def attach_request_file(deal, name: str, data: bytes) -> None:
    """Файл письма клиента — исходник заявки: виден в «Расчёте» (`deal_request_files`)."""
    from django.core.files.base import ContentFile

    from sourcing.models import Attachment, AttachmentKind

    Attachment.objects.create(
        deal=deal, kind=AttachmentKind.SOURCE, original_filename=name, file=ContentFile(data, name=name)
    )
