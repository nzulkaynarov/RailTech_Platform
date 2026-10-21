"""Мастер первого запуска ERP: создание СВОЕЙ компании администратором (FIX-65).

На чистой установке своей компании нет (`core.tenant.own_company() is None`), а администратор,
пришедший по SSO, — суперпользователь без членства. Раньше компанию заводили руками в
`manage.py shell`; теперь это один экран. Эталоны: Odoo «Set up your company» при первом входе,
ERPNext «Setup Wizard» (company name / abbreviation / country).

Правила:
  * создать можно только пока своей компании нет — иначе `OWN_COMPANY_ALREADY_EXISTS` (повтор безопасен);
  * только суперпользователь — решает вызывающее представление;
  * всё в одной транзакции под рекомендательной блокировкой Postgres: два параллельных запроса не
    создадут две компании-продавца (после этого `own_company_id()` стал бы неоднозначным).
"""

from typing import Any, Dict, Optional, Tuple

from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction

from accounts.constants import SELLER_COMPANY_TYPES, WorkspaceRoleCode
from accounts.models import Company, CompanyType, CustomUser
from core.audit import log_admin_action
from core.tenant import own_company_id

from .members import add_company_member

# Произвольное, но постоянное число — ключ блокировки «создаётся своя компания».
_SETUP_LOCK_KEY = 6_500_065


def is_setup_required() -> bool:
    """Своей компании ещё нет. Неоднозначность (несколько продавцов без `OWN_COMPANY_ID`) — не «первый
    запуск», а ошибка настройки: мастер её не чинит."""
    from core.tenant import own_company

    try:
        return own_company() is None
    except ImproperlyConfigured:
        return False


def create_own_company(user: CustomUser, data: Dict[str, Any]) -> Tuple[Optional[Company], Optional[str]]:
    """Создать свою компанию и сделать `user` её владельцем. Возвращает (компания, None) или (None, код ошибки)."""
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_SETUP_LOCK_KEY])
        if not is_setup_required():
            return None, "OWN_COMPANY_ALREADY_EXISTS"

        company = Company.objects.create(
            name=data["name"],
            inn=data.get("inn") or None,
            legal_address=data.get("legal_address", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
        )
        for code in SELLER_COMPANY_TYPES:
            company_type, _created = CompanyType.objects.get_or_create(code=code, defaults={"name": str(code)})
            company.types.add(company_type)

        _member, error = add_company_member(user, company, WorkspaceRoleCode.OWNER, is_primary=True)
        if error:
            transaction.set_rollback(True)
            return None, error
        # `OWN_COMPANY_ID` указывает на другую компанию — созданная не стала бы своей, и мастер
        # показывался бы снова. Откатываем и говорим причину.
        if own_company_id() != company.pk:
            transaction.set_rollback(True)
            return None, "OWN_COMPANY_ID_MISMATCH"

        log_admin_action(
            entity_type="company",
            entity_id=company.id,
            action="Создана своя компания (мастер первого запуска)",
            detail=f"{company.name}: первоначальная настройка ERP",
            event_code="admin.company.own_created",
            event_params={"company_name": company.name},
            actor=user,
            after={"name": company.name, "inn": company.inn},
            company_id=company.id,
        )
        return company, None
