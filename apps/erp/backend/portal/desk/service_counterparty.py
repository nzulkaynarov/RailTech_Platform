"""Карточка контрагента — одна компания во всех ролях (ADR-0028, СУЩ-2.5).

Роли — не отдельные записи, а отметки одной компании: «клиент» (книга продавца, заводит CRM), «поставщик» и
«изготовитель» (типы `SUPPLIER`, `MANUFACTURER` — отмечает сотрудник), «партнёр с кабинетом» (отношение `partner`,
появляется по заявке или приглашению), «организация» (тип `ORGANIZATION` — адресат письма без сделок: госорган, банк;
заводит сотрудник прямо из письма, СУЩ-2.6). Люди — контакты компании; счета — `CompanyBankAccount`; бренды — справочник
«Бренды» со ссылкой на компанию. Телефоны и почта людей здесь не отдаются: их открывают по одному (`parties/people`).
Номер счёта полностью видит держатель `finance.view` или `finance.payment`, остальные — последние 4 знака.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import transaction
from integration.models import CrmClientMapping
from parties.banking import grouped, masked
from parties.models import Company, CompanyType
from parties.models.relationships import CompanyRelationship, RelationshipRole, RelationshipStatus

from accounts.services.permissions import staff_has_permission
from catalog.desk.audit import record
from catalog.desk.items import ItemError
from catalog.models import Manufacturer, SupplierOffer

#: Роли, которые сотрудник отмечает сам; остальные приходят из процессов (CRM, заявка в партнёры).
EDITABLE_ROLES = {"supplier": "SUPPLIER", "manufacturer": "MANUFACTURER"}
_TYPE_NAMES = {"SUPPLIER": "Поставщик", "MANUFACTURER": "Изготовитель", "ORGANIZATION": "Организация"}
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
        "organization": "ORGANIZATION" in codes,
    }


def roles_for(companies, client_ids: set) -> dict[int, dict]:
    """Роли пачки компаний (список выбора): те же отметки, что у `roles_of`, пятью запросами на страницу, а не на строку."""
    ids = [c.pk for c in companies]
    codes: dict[int, set] = {}
    for company_id, code in Company.objects.filter(pk__in=ids).values_list("pk", "types__code"):
        if code:
            codes.setdefault(company_id, set()).add(code)
    offered = set(SupplierOffer.objects.filter(supplier__in=ids).values_list("supplier", flat=True))
    partners = set(
        CompanyRelationship.objects.filter(
            company__in=ids,
            role=RelationshipRole.PARTNER,
            status__in=(RelationshipStatus.INVITED, RelationshipStatus.ACTIVE),
        ).values_list("company", flat=True)
    )
    return {
        pk: {
            "client": pk in client_ids,
            "supplier": "SUPPLIER" in codes.get(pk, ()) or pk in offered,
            "manufacturer": "MANUFACTURER" in codes.get(pk, ()),
            "partner": pk in partners,
            "organization": "ORGANIZATION" in codes.get(pk, ()),
        }
        for pk in ids
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


@transaction.atomic
def create_organization(data: dict, *, actor) -> Company:
    """Завести организацию-адресата из письма (ADR-0028 п. 5, СУЩ-2.6): название, ИНН или рег. номер, страна, адрес.

    Компания без сделок, роль «Организация»; людей и счета ей добавляют в карточке. Дубль по ИНН, по паре
    «страна — рег. номер» или — без ИНН — по названию — 409 `COMPANY_EXISTS`: такую компанию выбирают из списка.
    """
    from catalog.desk.suppliers import _country

    name = " ".join((data.get("name") or "").split())
    if not name:
        raise ItemError("COMPANY_NAME_REQUIRED", "name")
    inn = (data.get("tin") or "").strip() or None
    registration_number = (data.get("registration_number") or "").strip()
    if inn and not re.match(settings.INN_VALIDATION_REGEX, inn):
        raise ItemError("TIN_INVALID", "tin")
    country = _country(data.get("country_id"))
    role = data.get("role") or "organization"
    if role not in ("organization", *EDITABLE_ROLES):
        raise ItemError("ROLE_NOT_EDITABLE", "role")
    if role in EDITABLE_ROLES and not staff_has_permission(actor, "supply.manage"):
        raise ItemError("ROLE_PERMISSION_REQUIRED", "role")
    # дубль ищется среди ВСЕХ компаний, не только видимых в списке выбора; id найденной — в ответе (`existing_id`)
    twin = None
    if inn:
        twin = Company.objects.filter(inn=inn).first()
        taken_field = "tin"
    if twin is None and registration_number:
        twin = Company.objects.filter(registration_number__iexact=registration_number, country=country).first()
        taken_field = "registration_number"
    if twin is None and not inn and not registration_number:
        twin = Company.objects.filter(name__iexact=name).first()
        taken_field = "name"
    if twin is not None:
        raise ItemError("COMPANY_EXISTS", taken_field, {"existing_id": twin.pk})
    company = Company.objects.create(
        name=name,
        inn=inn,
        registration_number=registration_number,
        country=country,
        legal_address=(data.get("legal_address") or "").strip(),
        is_registered=False,  # заведена сотрудником, входа нет
    )
    code = "ORGANIZATION" if role == "organization" else EDITABLE_ROLES[role]
    kind, _ = CompanyType.objects.get_or_create(code=code, defaults={"name": _TYPE_NAMES[code]})
    company.types.add(kind)
    record(
        actor,
        entity="company",
        instance=company,
        event="created",
        # the source (letter, request form, brand) is not known here, so the entry names only the fact
        action="Организация заведена" if role == "organization" else "Контрагент заведён",
        before=None,
        after={"name": name, "inn": inn, "registration_number": registration_number or None, "role": role},
        detail=name,
    )
    return company


#: Реквизиты, которые сотрудник правит в карточке контрагента (СУЩ-2.7): их ведёт ERP, CRM получает снимок
REQUISITE_FIELDS = ("name", "tin", "registration_number", "country_id", "legal_address")


@transaction.atomic
def update_requisites(company: Company, data: dict, *, actor) -> Company:
    """Название, ИНН, рег. номер, страна и адрес компании-контрагента (ADR-0028 п. 6, СУЩ-2.7).

    Владелец реквизитов — ERP: правка сохраняется здесь, CRM получает снимок `company.updated` (сигнал модели). Пустое
    название — 400 `COMPANY_NAME_REQUIRED`; такой ИНН или пара «страна — рег. номер» у другой компании — 409 `COMPANY_EXISTS`.
    """
    from catalog.desk.suppliers import _country

    before = {
        "name": company.name,
        "inn": company.inn,
        "registration_number": company.registration_number or None,
        "country": company.country.code if company.country_id else None,
        "legal_address": company.legal_address or None,
    }
    if "name" in data:
        name = " ".join((data.get("name") or "").split())
        if not name:
            raise ItemError("COMPANY_NAME_REQUIRED", "name")
        company.name = name
    if "tin" in data:
        inn = (data.get("tin") or "").strip() or None
        if inn and not re.match(settings.INN_VALIDATION_REGEX, inn):
            raise ItemError("TIN_INVALID", "tin")
        company.inn = inn
    if "registration_number" in data:
        company.registration_number = (data.get("registration_number") or "").strip()
    if "country_id" in data:
        company.country = _country(data.get("country_id"))
    if "legal_address" in data:
        company.legal_address = (data.get("legal_address") or "").strip()
    others = Company.objects.exclude(pk=company.pk)
    if company.inn and others.filter(inn=company.inn).exists():
        raise ItemError("COMPANY_EXISTS", "tin")
    if (
        company.registration_number
        and others.filter(
            registration_number__iexact=company.registration_number, country_id=company.country_id
        ).exists()
    ):
        raise ItemError("COMPANY_EXISTS", "registration_number")
    company.save()
    after = {
        "name": company.name,
        "inn": company.inn,
        "registration_number": company.registration_number or None,
        "country": company.country.code if company.country_id else None,
        "legal_address": company.legal_address or None,
    }
    if after != before:
        record(
            actor,
            entity="company",
            instance=company,
            event="updated",
            action="Реквизиты контрагента изменены",
            before=before,
            after=after,
            detail=company.name,
        )
    return company
