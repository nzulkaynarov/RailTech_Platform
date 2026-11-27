"""Реквизиты компании-контрагента → CRM: событие `uz.railtech.erp.company.updated.v1` (ADR-0028 п. 6, СУЩ-2.7).

ERP — владелец названия, ИНН и реквизитов компании; CRM держит их проекцию у клиента со ссылкой `erp_company_id`. Компания
сохраняется из многих мест (карточка контрагента, поставщик, организация из письма, «Компания» кабинета), поэтому снимок
пишет сигнал модели: до сохранения запоминаются прежние значения, после — при их изменении снимок уходит в outbox той же
транзакции. Публикуется только компания, связанная с клиентом CRM (`CrmClientMapping`): остальным CRM не нужна. Своя
компания ERP — не контрагент, её реквизиты уходят событием бланка. Схема — `packages/contracts/events/erp/company.updated.v1.json`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from parties import do_not_work

COMPANY_UPDATED = "uz.railtech.erp.company.updated.v1"

#: Поля, которыми ERP владеет и которые проецирует CRM
TRACKED = (
    "name",
    "inn",
    "registration_number",
    "country_id",
    "legal_address",
    # Х-8: отметка «Не работать» едет в том же снимке — CRM показывает её в карточке клиента
    "do_not_work_at",
    "do_not_work_by_id",
    "do_not_work_reason",
    "do_not_work_until",
    # ТЕСТ-1: «Тестовая» едет в том же снимке — CRM прячет клиента из рабочих списков
    "is_test",
)


def _values(company) -> Tuple[Any, ...]:
    return tuple(getattr(company, field) for field in TRACKED)


def _text(value: Any, limit: int) -> Optional[str]:
    text = str(value or "").strip()
    return text[:limit] or None


def company_data(company, user=None) -> Dict[str, Any]:
    """`data` события: снимок реквизитов компании целиком."""
    from integration.services.event_builders import build_actor

    country = company.country.code if company.country_id else None
    return {
        "erp_company_id": int(company.pk),
        "actor": build_actor(user),
        "company": {
            "name": _text(company.name, 255) or str(company.pk),
            "inn": _text(company.inn, 32),
            "registration_number": _text(company.registration_number, 64),
            "country": country if country and len(country) == 2 else None,
            "legal_address": _text(company.legal_address, 1000),
            "updated_at": company.updated_at.isoformat(),
            # Х-8: `null` — отметки нет или снята; срок CRM сверяет сам (отметка действует до `until`)
            "do_not_work": do_not_work.facts(company, only_active=False),
            "is_test": bool(company.is_test),
        },
    }


def publish_company(company, user=None):
    """Снимок реквизитов в outbox текущей транзакции; компания без клиента CRM и своя компания — `None`."""
    from integration.bus import get_bus
    from integration.models import CrmClientMapping

    from core.tenant import own_company_id

    if company.pk is None or own_company_id() == company.pk:
        return None
    if not CrmClientMapping.objects.filter(company_id=company.pk).exists():
        return None
    with transaction.atomic():
        return get_bus().publish(COMPANY_UPDATED, company_data(company), subject=f"company/{int(company.pk)}")


def _remember(sender, instance, **kwargs) -> None:
    if instance.pk is None:
        instance._rt_requisites = None
        return
    row = sender.objects.filter(pk=instance.pk).values_list(*TRACKED).first()
    instance._rt_requisites = tuple(row) if row else None


def _publish_if_changed(sender, instance, created, raw=False, **kwargs) -> None:
    if raw:  # загрузка фикстур
        return
    before = getattr(instance, "_rt_requisites", None)
    if not created and before == _values(instance):
        return
    publish_company(instance)


def connect() -> None:
    from parties.models import Company

    pre_save.connect(_remember, sender=Company, dispatch_uid="rt_company_requisites_before")
    post_save.connect(_publish_if_changed, sender=Company, dispatch_uid="rt_company_requisites_after")
