"""Карточка контрагента — одна компания во всех ролях (ADR-0028, СУЩ-2.5).

Роли — не отдельные записи, а отметки одной компании: «клиент» (книга продавца, заводит CRM), «поставщик» и
«изготовитель» (типы `SUPPLIER`, `MANUFACTURER` — отмечает сотрудник), «партнёр с кабинетом» (отношение `partner`,
появляется по заявке или приглашению). Люди — контакты компании; счета — `CompanyBankAccount`; бренды — справочник
«Бренды» со ссылкой на компанию. Телефоны и почта людей здесь не отдаются: их открывают по одному (`parties/people`).
Номер счёта полностью видит держатель `finance.view` или `finance.payment`, остальные — последние 4 знака.
"""

from __future__ import annotations

from django.db import transaction
from integration.models import CrmClientMapping
from parties.banking import grouped, masked
from parties.models import Company, CompanyType
from parties.models.relationships import RelationshipRole, RelationshipStatus

from accounts.services.permissions import staff_has_permission
from catalog.desk.audit import record
from catalog.desk.items import ItemError
from catalog.models import Manufacturer, SupplierOffer

#: Роли, которые сотрудник отмечает сам; остальные приходят из процессов (CRM, заявка в партнёры).
EDITABLE_ROLES = {"supplier": "SUPPLIER", "manufacturer": "MANUFACTURER"}
_TYPE_NAMES = {"SUPPLIER": "Поставщик", "MANUFACTURER": "Изготовитель"}
_FULL_ACCOUNT = ("finance.view", "finance.payment")


def roles_of(company: Company, client_ids: set) -> dict:
    codes = set(company.types.values_list("code", flat=True))
    has_offers = SupplierOffer.objects.filter(supplier=company).exists()
    return {
        "client": company.pk in client_ids,
        "supplier": "SUPPLIER" in codes or has_offers,
        "manufacturer": "MANUFACTURER" in codes,
        "partner": company.relationships.filter(
            role=RelationshipRole.PARTNER,
            status__in=(RelationshipStatus.INVITED, RelationshipStatus.ACTIVE),
        ).exists(),
    }


def _account_row(account, *, full: bool) -> dict:
    return {
        "id": account.pk,
        "currency": account.currency.code if account.currency_id else None,
        "bank_name": account.bank_name or "",
        "bank_country": account.bank_country.code if account.bank_country_id else None,
        "account": grouped(account.account) if full else masked(account.account),
        "mfo": account.mfo or "",
        "swift": account.swift or "",
        "is_default": account.is_default,
    }


def card(company: Company, client_ids: set, user) -> dict:
    full = staff_has_permission(user, _FULL_ACCOUNT)
    mapping = CrmClientMapping.objects.filter(company=company).values_list("crm_client_id", flat=True).first()
    people = company.contacts.order_by("-is_primary", "name", "pk")
    accounts = (
        company.bank_accounts.filter(is_active=True)
        .select_related("currency", "bank_country")
        .order_by("-is_default", "currency__code", "pk")
    )
    return {
        "id": company.pk,
        "name": company.name,
        "inn": company.inn or None,
        "registration_number": company.registration_number or None,
        "country": company.country.name if company.country_id else None,
        "legal_address": company.legal_address or None,
        "crm_client_id": mapping,
        "roles": roles_of(company, client_ids),
        "people": [
            {
                "id": person.pk,
                "name": person.name,
                "position": person.position or None,
                "is_primary": person.is_primary,
                "has_cabinet": bool(person.can_act or person.is_admin),
                "has_phone": bool(person.phone),
                "has_email": bool(person.email),
            }
            for person in people
        ],
        "bank_accounts": [_account_row(account, full=full) for account in accounts],
        "accounts_masked": not full,
        "brands": [
            {"id": brand.pk, "name": brand.name}
            for brand in Manufacturer.objects.filter(company=company).order_by("name")
        ],
    }


@transaction.atomic
def set_role(company: Company, role: str, on: bool, *, actor) -> None:
    """Отметить или снять роль «поставщик» или «изготовитель». Снять нельзя, пока роль занята данными."""
    code = EDITABLE_ROLES.get(role)
    if code is None:
        raise ItemError("ROLE_NOT_EDITABLE", "role")
    has = company.types.filter(code=code).exists()
    if not on:
        # Роль держат данные, а не только отметка: предложения делают компанию поставщиком, бренды — изготовителем
        if code == "SUPPLIER" and SupplierOffer.objects.filter(supplier=company).exists():
            raise ItemError("ROLE_IN_USE", "role")
        if code == "MANUFACTURER" and Manufacturer.objects.filter(company=company).exists():
            raise ItemError("ROLE_IN_USE", "role")
    if on == has:
        return
    company_type, _ = CompanyType.objects.get_or_create(code=code, defaults={"name": _TYPE_NAMES[code]})
    if on:
        company.types.add(company_type)
    else:
        company.types.remove(company_type)
    record(
        actor,
        entity="company",
        instance=company,
        event="updated",
        action=f"Роль «{_TYPE_NAMES[code]}» {'отмечена' if on else 'снята'}",
        before={"role": role, "on": has},
        after={"role": role, "on": on},
    )
