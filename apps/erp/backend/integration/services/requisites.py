"""Реквизиты клиента ведёт CRM (ORCHESTRATOR §3 п. 16, решение архитектора 2026-10-23): в ERP они только для чтения.

Название и ИНН компании, связанной с клиентом CRM (`CrmClientMapping`), приходят событием `client.updated` (проекция,
`crm_projections.apply_client_snapshot`). API ERP — internal (`PATCH /accounts/companies/{id}/`) и portal
(`PUT /company`) — отклоняет их правку кодом `REQUISITES_MANAGED_BY_CRM`: старый клиент не должен увидеть «сохранено»,
пока при следующем снимке CRM значение вернётся. Компания без сопоставления с CRM (заведена сотрудником ERP, своя
компания-продавец) правится как раньше — менять её реквизиты негде, кроме ERP. Остальные реквизиты (адрес, банк, МФО…) в
схеме `client.*.v1` не переносятся и правятся в ERP; правка реквизитов из Cabinet через CRM — позже.
"""

from __future__ import annotations

from typing import Any, List, Mapping

#: Поля компании, которыми владеет CRM и которые переносит `uz.railtech.crm.client.updated.v1`.
CRM_OWNED_COMPANY_FIELDS = ("name", "inn")

REQUISITES_MANAGED_BY_CRM = "REQUISITES_MANAGED_BY_CRM"


def _norm(field: str, value: Any):
    text = ("" if value is None else str(value)).strip()
    return (text or None) if field == "inn" else text


def changed_crm_owned_fields(company: Any, data: Mapping[str, Any]) -> List[str]:
    """Поля из `data`, которыми владеет CRM и значение которых отличается от текущего у компании, связанной с CRM."""
    from ..models import CrmClientMapping

    if not CrmClientMapping.objects.filter(company_id=company.pk).exists():
        return []
    return [
        field
        for field in CRM_OWNED_COMPANY_FIELDS
        if field in data and _norm(field, data[field]) != _norm(field, getattr(company, field))
    ]
