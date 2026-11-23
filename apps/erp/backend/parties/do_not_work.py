"""Отметка «Не работать» у контрагента (план Х-8, DECISIONS 2026-11-23).

Отметка — факты на компании: `do_not_work_at` (когда), `do_not_work_by` (кто), `do_not_work_reason` (причина, обязательна),
`do_not_work_until` (необязательная дата, после которой отметка не действует). Действует ли она — считает `is_marked` из
этих фактов, отдельного флага нет. Новые КП, договор, заказ поставщику и заявка у отмеченной компании отказываются
сервером (409 `COMPANY_DO_NOT_WORK` с причиной и тем, кто отметил); документы, уже идущие в работе, не отменяются.
Отказ ставится на создание модели (`pre_save`), а не по местам вызова: так им покрыты портал, интеграция, MCP и десктоп.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from django.db.models.signals import pre_save
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import APIException

CODE = "COMPANY_DO_NOT_WORK"


def is_marked(company, today: Optional[date] = None) -> bool:
    """Отметка действует: поставлена и срок (если задан) не вышел."""
    if company is None or company.do_not_work_at is None:
        return False
    until = company.do_not_work_until
    return until is None or until >= (today or timezone.localdate())


def _person(user) -> Optional[str]:
    if user is None:
        return None
    name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return (name or getattr(user, "email", "") or str(user)).strip() or None


def facts(company, *, only_active: bool = True) -> Optional[Dict[str, Any]]:
    """Факты отметки для карточки и события шины; `None` — отметки нет или (при `only_active`) срок вышел."""
    if company.do_not_work_at is None or (only_active and not is_marked(company)):
        return None
    return {
        "reason": company.do_not_work_reason,
        "set_by": _person(company.do_not_work_by) if company.do_not_work_by_id else None,
        "set_at": company.do_not_work_at.isoformat(),
        "until": company.do_not_work_until.isoformat() if company.do_not_work_until else None,
    }


class CompanyDoNotWork(APIException):
    """409: с компанией не работаем; в теле — причина и кто отметил (текст для сотрудника собирает Платформа)."""

    status_code = status.HTTP_409_CONFLICT
    default_code = CODE

    def __init__(self, company):
        super().__init__(CODE)
        self.company_id = company.pk
        # тело ответа — как есть, без приведения значений к строкам (`None` остаётся `null`)
        self.detail = {"detail": CODE, "company_id": company.pk, "do_not_work": facts(company)}


def fresh(company):
    """Компания из базы прямо сейчас: объект в руках вызывающего мог быть прочитан до того, как отметку поставили."""
    if company is None or company.pk is None:
        return None
    from parties.models import Company

    return Company.objects.select_related("do_not_work_by").filter(pk=company.pk).first()


def ensure_may_work(company) -> None:
    """Отказ, если у компании действует «Не работать» (читается из базы заново); `None` проходит."""
    current = fresh(company)
    if is_marked(current):
        raise CompanyDoNotWork(current)


def _guard(company_getter):
    def handler(sender, instance, raw=False, **kwargs) -> None:
        if raw or not instance._state.adding:
            return
        ensure_may_work(company_getter(instance))

    return handler


def connect() -> None:
    """Отказ создания КП, договора, заказа поставщику и заявки (сделки) у отмеченной компании."""
    from sales.models import Contract, Deal, Quote
    from supply.models import SupplierOrder

    pairs = (
        (Deal, lambda deal: deal.company),
        (Quote, lambda quote: quote.deal.company if quote.deal_id else None),
        (Contract, lambda contract: contract.deal.company if contract.deal_id else None),
        (SupplierOrder, lambda order: order.supplier),
    )
    for model, getter in pairs:
        pre_save.connect(
            _guard(getter), sender=model, weak=False, dispatch_uid=f"rt_do_not_work_{model.__name__.lower()}"
        )


class DoNotWorkFacts(serializers.Serializer):
    """Факты отметки «Не работать» в ответах API: карточка контрагента, карточка проекта."""

    reason = serializers.CharField()
    set_by = serializers.CharField(allow_null=True, help_text="Кто поставил отметку (имя сотрудника)")
    set_at = serializers.DateTimeField()
    until = serializers.DateField(allow_null=True, help_text="До какой даты действует; `null` — без срока")
