"""Название и ИНН клиента из Cabinet не правятся (портальный `PUT /company` — `REQUISITES_MANAGED_BY_CRM`).

С СУЩ-2.7 (ADR-0028 п. 6) названием и ИНН компании владеет ERP: сотрудник правит их в ERP, CRM получает проекцию событием
`uz.railtech.erp.company.updated.v1` (`parties.company_events`). Контакт клиента в кабинете юридическое лицо своей
компании не меняет: правка названия и ИНН компании, связанной с клиентом CRM (`CrmClientMapping`), по-прежнему
отклоняется — через сотрудника. Код ответа портала прежний (контракт `erp-portal.yaml`).
"""

from __future__ import annotations

from typing import Any, List, Mapping

#: Поля компании, которые контакт клиента в кабинете не правит (юридическое лицо — через сотрудника).
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
