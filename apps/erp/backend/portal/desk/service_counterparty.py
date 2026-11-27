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
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from integration.models import CrmClientMapping
from parties import do_not_work, pictures
from parties.banking import grouped, masked
from parties.models import Company, CompanyType
from portal.desk import company_roles

from accounts.services.permissions import staff_has_permission
from catalog.desk.audit import record
from catalog.desk.items import ItemError
from catalog.models import Manufacturer, SupplierOffer

#: Роли, которые сотрудник отмечает сам; остальные приходят из процессов (CRM, заявка в партнёры).
EDITABLE_ROLES = {"supplier": "SUPPLIER", "manufacturer": "MANUFACTURER"}
_TYPE_NAMES = {"SUPPLIER": "Поставщик", "MANUFACTURER": "Изготовитель", "ORGANIZATION": "Организация"}
_FULL_ACCOUNT = ("finance.view", "finance.payment")


def _states(company_ids, client_ids: set) -> dict[int, list[dict]]:
    """Роли с состояниями (`company_roles`); клиентом считается только то, что в книге продавца (`client_ids`)."""
    return {
        pk: [s for s in states if not (s["role"] == "client" and pk not in client_ids)]
        for pk, states in company_roles.role_states_for(company_ids).items()
    }


def _flags(pk: int, states: list[dict], codes: set, offered: bool) -> dict:
    partner = any(s["role"] == "partner" and s["state"] != "suspended" for s in states)
    return {
        "client": any(s["role"] == "client" for s in states),
        "supplier": "SUPPLIER" in codes or offered,
        "manufacturer": "MANUFACTURER" in codes,
        "partner": partner,
        "organization": "ORGANIZATION" in codes,
    }


def roles_of(company: Company, client_ids: set) -> dict:
    codes = set(company.types.values_list("code", flat=True))
    has_offers = SupplierOffer.objects.filter(supplier=company).exists()
    return _flags(company.pk, _states([company.pk], client_ids)[company.pk], codes, has_offers)


def roles_for(companies, client_ids: set) -> dict[int, dict]:
    """Роли пачки компаний (список выбора): те же отметки, что у `roles_of`, пятью запросами на страницу, а не на строку."""
    ids = [c.pk for c in companies]
    codes: dict[int, set] = {}
    for company_id, code in Company.objects.filter(pk__in=ids).values_list("pk", "types__code"):
        if code:
            codes.setdefault(company_id, set()).add(code)
    offered = set(SupplierOffer.objects.filter(supplier__in=ids).values_list("supplier", flat=True))
    states = _states(ids, client_ids)
    return {pk: _flags(pk, states[pk], codes.get(pk, set()), pk in offered) for pk in ids}


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
        "logo_version": pictures.version(company.logo),
        "roles": roles_of(company, client_ids),
        "role_states": _states([company.pk], client_ids)[company.pk],
        "cabinet": company_roles.cabinet_truth(company),
        "people": [
            {
                "id": person.pk,
                "name": person.name,
                "position": person.position or None,
                "is_primary": person.is_primary,
                "has_cabinet": bool(person.can_act or person.is_admin),
                "has_phone": bool(person.phone),
                "has_email": bool(person.email),
                "photo_version": pictures.version(person.photo),
            }
            for person in people
        ],
        "bank_accounts": [_account_row(account, full=full) for account in accounts],
        "accounts_masked": not full,
        "brands": [
            {"id": brand.pk, "name": brand.name}
            for brand in Manufacturer.objects.filter(company=company).order_by("name")
        ],
        "do_not_work": do_not_work.facts(company),
        "is_test": bool(company.is_test),
        "contract_term": _contract_term(company),
    }


def _contract_term(company) -> Optional[dict]:
    """ДС-1: срок действующего (или последнего) договора с компанией; `None` — подписанных договоров со сроком нет."""
    from crm.services import contract_term

    return contract_term.counterparty_term(company)


def _grant_client(company: Company, on: bool, *, actor) -> None:
    """«+ Клиент» (КОНТР-1б): компания, заведённая письмом или мастером как «организация», получает роль клиента — ей
    открывается кабинет клиента. Снять роль — только «Не клиент» (с закрытием заявок и журналом)."""
    if not on:
        raise ItemError("ROLE_NOT_EDITABLE", "role")
    client_type, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    if company.types.filter(code="CLIENT").exists():
        return
    company.types.add(client_type)
    company.client_role_removed_at = None
    company.client_role_removed_by = None
    company.save(update_fields=["client_role_removed_at", "client_role_removed_by"])
    record(
        actor,
        entity="company",
        instance=company,
        event="client_role_granted",
        action="Роль «Клиент» отмечена",
        before={"role": "client", "on": False},
        after={"role": "client", "on": True},
    )


@transaction.atomic
def set_role(company: Company, role: str, on: bool, *, actor) -> None:
    """Отметить или снять роль «поставщик» или «изготовитель». Снять нельзя, пока роль занята данными."""
    if role == "client":
        _grant_client(company, on, actor=actor)
        return
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


#: Причина «Не работать» — текст для коллег, не заметка на полях: короткий отказ без причины не принимается
REASON_MAX = 1000


@transaction.atomic
def set_do_not_work(company: Company, data: dict, *, actor) -> Company:
    """Отметить «Не работать» (Х-8): причина обязательна, дата «до» — по желанию (не раньше сегодняшней).

    Повторная отметка заменяет прежнюю (новая причина, срок, автор). Пустая причина — 400 `REASON_REQUIRED`, дата в прошлом —
    400 `UNTIL_PAST`. Отметка не отменяет документы в работе: она отказывает только новым КП, договору, заказу и заявке.
    """
    reason = " ".join((data.get("reason") or "").split())[:REASON_MAX]
    if not reason:
        raise ItemError("REASON_REQUIRED", "reason")
    until = data.get("until")
    if until is not None and until < timezone.localdate():
        raise ItemError("UNTIL_PAST", "until")
    company = Company.objects.select_for_update().get(pk=company.pk)
    before = do_not_work.facts(company)
    company.do_not_work_at = timezone.now()
    company.do_not_work_by = actor if getattr(actor, "pk", None) else None
    company.do_not_work_reason = reason
    company.do_not_work_until = until
    company.save()
    record(
        actor,
        entity="company",
        instance=company,
        event="updated",
        action="Контрагенту поставлено «Не работать»",
        before=before,
        after=do_not_work.facts(company),
        detail=company.name,
    )
    return company


@transaction.atomic
def clear_do_not_work(company: Company, *, actor) -> Company:
    """Снять «Не работать»; отметки нет — ничего не меняется и не пишется (повтор безопасен)."""
    company = Company.objects.select_for_update().get(pk=company.pk)
    if company.do_not_work_at is None:
        return company
    before = do_not_work.facts(company, only_active=False)
    company.do_not_work_at = None
    company.do_not_work_by = None
    company.do_not_work_reason = ""
    company.do_not_work_until = None
    company.save()
    record(
        actor,
        entity="company",
        instance=company,
        event="updated",
        action="С контрагента снято «Не работать»",
        before=before,
        after=None,
        detail=company.name,
    )
    return company


@transaction.atomic
def set_test(company: Company, on: bool, *, actor) -> Company:
    """«Тестовая» (ТЕСТ-1): отметить компанию или снять отметку. Ничего не удаляется: компания уходит из рабочих списков,
    счётчиков и отчётов и видна по фильтру «Тестовые». Повтор безопасен — ничего не меняется и не пишется; действие
    пишется в журнал, CRM получает отметку в снимке `company.updated`."""
    company = Company.objects.select_for_update().get(pk=company.pk)
    if company.is_test == bool(on):
        return company
    company.is_test = bool(on)
    company.save()
    record(
        actor,
        entity="company",
        instance=company,
        event="updated",
        action="Контрагент отмечен как тестовый" if on else "С контрагента снята отметка «Тестовая»",
        before={"is_test": not on},
        after={"is_test": bool(on)},
        detail=company.name,
    )
    return company
