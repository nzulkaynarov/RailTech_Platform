"""Доступ партнёра (карточка поставщика) в кабинет: состояние, контакты, приглашение, приостановка (ADR-0022).

Отношение заводит только сотрудник. «Пригласить» — это создать или вернуть отношение `partner` и отправить контакту письмо
с кодом входа тем же механизмом, что клиенту (`portal.services.invitation.invite_contact`, язык письма — по контакту).
Telegram партнёрам на срезе не нужен: приглашение уходит только на e-mail. Права партнёра — список включённых модулей на
отношении: его настраивает сотрудник (решение владельца 2026-11-04), включить можно только модуль из шаблона роли
(`portal/services/roles.py`); кто и когда менял — pghistory и журнал.
"""

from __future__ import annotations

import pghistory
from django.db import transaction
from django.utils import timezone
from integration.services import partner_client
from integration.services.partner_client import crm_client_state, lock_company, request_client_in_crm
from parties.models import (
    Company,
    CompanyRelationship,
    Contact,
    PartnerKind,
    RelationshipRole,
    RelationshipStatus,
    active_contact_q,
)
from portal.services.access import cabinet_company_q, company_access
from portal.services.invitation import invite_contact
from portal.services.roles import PARTNER, PARTNER_DEFAULT_TOGGLEABLE, PARTNER_TOGGLEABLE, ROLE_MODULES, partner_toggled

from catalog.constants import PriceVisibility
from catalog.desk.audit import record

LANGUAGES = ("ru", "uz", "en")
ROLE = RelationshipRole.PARTNER
KINDS = tuple(PartnerKind.values)

CONTACT_FIELDS = ("name", "email", "phone", "language", "can_act")


class AccessError(Exception):
    """Отказ: `code` — машинный код ответа `{"detail": КОД}`, `status` — HTTP-статус."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _person(user) -> dict | None:
    if user is None:
        return None
    name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return {"id": user.pk, "name": name or getattr(user, "email", "") or str(user.pk)}


def get_relationship(company: Company) -> CompanyRelationship | None:
    return (
        CompanyRelationship.objects.filter(company=company, role=ROLE)
        .select_related("responsible", "invited_by")
        .first()
    )


def contact_row(contact: Contact) -> dict:
    return {
        "id": contact.pk,
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "language": contact.language,
        "can_act": contact.can_act,
        "invited_at": contact.invited_at,
        "last_login_at": contact.last_login_at,
    }


def clean_modules(modules) -> list[str]:
    """Модули для отношения: список кодов из шаблона роли `partner`, без повторов, в порядке шаблона."""
    if not isinstance(modules, (list, tuple)) or not all(isinstance(m, str) for m in modules):
        raise AccessError("VALIDATION_ERROR")
    if set(modules) - set(ROLE_MODULES[PARTNER]):
        raise AccessError("MODULE_NOT_ALLOWED")
    return partner_toggled(modules)  # «Профиль» обязателен и в список переключателей не входит


def clean_price_visibility(value) -> str:
    """Цены товаров партнёра в каталоге: пусто — как у компании, иначе `cabinet` (показывать) или `on_request` (по запросу)."""
    if value in (None, ""):
        return ""
    if value not in PriceVisibility.values:
        raise AccessError("VALIDATION_ERROR")
    return value


def clean_kind(kind) -> str:
    if kind in (None, ""):
        return ""
    if kind not in KINDS:
        raise AccessError("VALIDATION_ERROR")
    return kind


def access_state(company: Company, *, can_manage: bool) -> dict:
    relationship = get_relationship(company)
    roles, modules = company_access(company.pk)
    contacts = Contact.objects.filter(active_contact_q(), company=company).order_by("name", "id")
    return {
        "company_id": company.pk,
        "company_name": company.name,
        "relationship": (
            None
            if relationship is None
            else {
                "role": relationship.role,
                "kind": relationship.kind,
                "modules": partner_toggled(relationship.modules),
                "catalog_price_visibility": relationship.catalog_price_visibility,
                "status": relationship.status,
                "invited_at": relationship.invited_at,
                "activated_at": relationship.activated_at,
                "suspended_at": relationship.suspended_at,
                "responsible": _person(relationship.responsible),
                "invited_by": _person(relationship.invited_by),
            }
        ),
        "contacts": [contact_row(c) for c in contacts],
        "partner_modules": {"allowed": list(PARTNER_TOGGLEABLE), "default": list(PARTNER_DEFAULT_TOGGLEABLE)},
        "cabinet_roles": roles,
        "cabinet_modules": modules,
        "crm_client": crm_client_state(company),
        "can_manage": can_manage,
    }


def _clean_contact(data: dict, *, partial: bool) -> dict:
    out: dict = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            raise AccessError("CONTACT_NAME_REQUIRED")
        out["name"] = name
    if "email" in data or not partial:
        email = (data.get("email") or "").strip().lower()
        if not email:
            raise AccessError("CONTACT_EMAIL_REQUIRED")
        out["email"] = email
    if "phone" in data:
        out["phone"] = (data.get("phone") or "").strip()
    if "language" in data:
        if data["language"] not in LANGUAGES:
            raise AccessError("VALIDATION_ERROR")
        out["language"] = data["language"]
    if "can_act" in data:
        out["can_act"] = bool(data["can_act"])
    return out


def _email_taken_in_company(company: Company, email: str, *, exclude_pk: int | None = None) -> bool:
    queryset = Contact.objects.filter(active_contact_q(), company=company, email__iexact=email)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.exists()


def create_contact(company: Company, data: dict, user) -> Contact:
    clean = _clean_contact(data, partial=False)
    if _email_taken_in_company(company, clean["email"]):
        raise AccessError("CONTACT_EXISTS", 409)
    contact = Contact.objects.create(
        company=company,
        preferred_channel="email",
        created_by=user,
        **{
            "can_act": True,
            **clean,
        },  # право действовать (заявки, загрузки) — по умолчанию; сотрудник выключает в блоке
    )
    record(
        user,
        entity="supplier_access",
        instance=company,
        event="contact_added",
        action="Контакт поставщика добавлен",
        before=None,
        after={"contact": contact.pk, "name": contact.name},
        detail=company.name,
    )
    return contact


def update_contact(company: Company, contact_id: int, data: dict, user) -> Contact:
    contact = Contact.objects.filter(active_contact_q(), company=company, pk=contact_id).first()
    if contact is None:
        raise AccessError("NOT_FOUND", 404)
    clean = _clean_contact(data, partial=True)
    if "email" in clean and _email_taken_in_company(company, clean["email"], exclude_pk=contact.pk):
        raise AccessError("CONTACT_EXISTS", 409)
    before = {name: getattr(contact, name) for name in CONTACT_FIELDS}
    for name, value in clean.items():
        setattr(contact, name, value)
    contact.save(update_fields=[*clean.keys(), "updated_at"] if clean else ["updated_at"])
    record(
        user,
        entity="supplier_access",
        instance=company,
        event="contact_updated",
        action="Контакт поставщика изменён",
        before={"contact": contact.pk, **before},
        after={"contact": contact.pk, **{name: getattr(contact, name) for name in CONTACT_FIELDS}},
        detail=company.name,
    )
    return contact


def _email_ambiguous(contact: Contact) -> bool:
    """Тот же адрес у активного контакта другой компании, допущенной в кабинет: ссылка входа открыла бы чужую компанию."""
    return (
        Contact.objects.filter(cabinet_company_q("company"), active_contact_q(), email__iexact=contact.email)
        .exclude(company_id=contact.company_id)
        .exists()
    )


class _Undo(Exception):
    """Письмо не ушло: состояние отношения откатывается вместе с остальным."""


def invite(company: Company, contact_id: int, user, *, modules=None, kind=None) -> dict:
    """Создать/вернуть отношение `partner` и отправить контакту письмо с кодом входа.

    `modules` — включённые партнёру модули (нет — у нового отношения значения шаблона по умолчанию, у существующего
    прежние), `kind` — метка вида партнёра. Не ушло письмо — отношение остаётся как было (приглашения не случилось). Повторное приглашение того же отношения
    безопасно: выпускается новый код, прежний гаснет.
    """
    contact = Contact.objects.filter(active_contact_q(), company=company, pk=contact_id).first()
    if contact is None:
        raise AccessError("NOT_FOUND", 404)
    if not contact.email:
        raise AccessError("CONTACT_EMAIL_REQUIRED")
    if _email_ambiguous(contact):
        raise AccessError("CONTACT_EMAIL_AMBIGUOUS", 409)

    wanted_modules = None if modules is None else clean_modules(modules)
    wanted_kind = None if kind is None else clean_kind(kind)
    now = timezone.now()
    try:
        with transaction.atomic(), pghistory.context(user=getattr(user, "pk", None), source="supplier_access"):
            # Общая блокировка по компании (PART-CRM): передача клиента из CRM и первое приглашение идут по очереди, иначе
            # передача успеет создать сопоставление, не увидев ещё не зафиксированное отношение партнёра.
            lock_company(company.pk)
            relationship = CompanyRelationship.objects.select_for_update().filter(company=company, role=ROLE).first()
            before = None if relationship is None else _snapshot(relationship)
            if relationship is None:
                relationship = CompanyRelationship(
                    company=company,
                    role=ROLE,
                    responsible=user,
                    invited_by=user,
                    invited_at=now,
                    modules=list(PARTNER_DEFAULT_TOGGLEABLE),
                )
            else:
                if relationship.responsible_id is None:
                    relationship.responsible = user
                relationship.invited_by = user
                relationship.invited_at = now
                relationship.suspended_at = None
            if wanted_modules is not None:
                relationship.modules = wanted_modules
            if wanted_kind is not None:
                relationship.kind = wanted_kind
            # Возврат после приостановки: бывавший в кабинете остаётся активным, новый — приглашённым.
            relationship.status = RelationshipStatus.ACTIVE if relationship.activated_at else RelationshipStatus.INVITED
            relationship.save()
            outcome = invite_contact(contact, actor=user, channel="email", language=contact.language)
            if outcome.error:
                raise _Undo(outcome.error)
            # Партнёр должен стать клиентом CRM (PART-CRM): просьба к CRM — в той же транзакции, что приглашение.
            request_client_in_crm(company, user)
            record(
                user,
                entity="supplier_access",
                instance=company,
                event="invited",
                action="Партнёр приглашён в кабинет",
                before=before,
                after={**_snapshot(relationship), "contact": contact.pk},
                detail=company.name,
            )
    except _Undo as undo:
        code = str(undo)
        raise AccessError(code) from None
    return access_state(company, can_manage=True)


def verify_crm_client(company: Company, user, *, confirm: bool) -> dict:
    """«Найден клиент CRM, связан по совпадению ИНН. Это та же компания?»: да — сопоставление проверено, заявки уходят;
    нет — сопоставление снято, CRM получает отказ и обычный запрос. Нечего проверять — 409 `NOTHING_TO_VERIFY`."""
    try:
        if confirm:
            released = partner_client.confirm_unverified(company, user)
        else:
            partner_client.reject_unverified(company, user)
            released = 0
    except partner_client.NothingToVerify:
        raise AccessError("NOTHING_TO_VERIFY", 409) from None
    record(
        user,
        entity="supplier_access",
        instance=company,
        event="crm_client_confirmed" if confirm else "crm_client_rejected",
        action="Связь с клиентом CRM подтверждена" if confirm else "Связь с клиентом CRM отклонена",
        before=None,
        after={"released_requests": released},
        detail=company.name,
    )
    return access_state(company, can_manage=True)


def _snapshot(relationship: CompanyRelationship) -> dict:
    return {
        "status": relationship.status,
        "kind": relationship.kind,
        "modules": partner_toggled(relationship.modules),
        "catalog_price_visibility": relationship.catalog_price_visibility,
    }


def update_relationship(company: Company, data: dict, user) -> dict:
    """Права и метка партнёра: модули, вид и цены его товаров в каталоге (PART-3). Действует сразу — без перевхода партнёра."""
    modules = clean_modules(data["modules"]) if "modules" in data else None
    kind = clean_kind(data["kind"]) if "kind" in data else None
    visibility = (
        clean_price_visibility(data["catalog_price_visibility"]) if "catalog_price_visibility" in data else None
    )
    with transaction.atomic(), pghistory.context(user=getattr(user, "pk", None), source="supplier_access"):
        relationship = CompanyRelationship.objects.select_for_update().filter(company=company, role=ROLE).first()
        if relationship is None:
            raise AccessError("NOT_FOUND", 404)
        before = _snapshot(relationship)
        if modules is not None:
            relationship.modules = modules
        if kind is not None:
            relationship.kind = kind
        if visibility is not None:
            relationship.catalog_price_visibility = visibility
        relationship.save()
        record(
            user,
            entity="supplier_access",
            instance=company,
            event="rights_changed",
            action="Права партнёра в кабинете изменены",
            before=before,
            after=_snapshot(relationship),
            detail=company.name,
        )
    return access_state(company, can_manage=True)


def suspend(company: Company, user) -> dict:
    """Закрыть вход: живые сессии гаснут на следующем запросе (`PortalAuthentication`)."""
    with transaction.atomic(), pghistory.context(user=getattr(user, "pk", None), source="supplier_access"):
        relationship = CompanyRelationship.objects.select_for_update().filter(company=company, role=ROLE).first()
        if relationship is None:
            raise AccessError("NOT_FOUND", 404)
        if relationship.status != RelationshipStatus.SUSPENDED:
            before = _snapshot(relationship)
            relationship.status = RelationshipStatus.SUSPENDED
            relationship.suspended_at = timezone.now()
            relationship.save()
            record(
                user,
                entity="supplier_access",
                instance=company,
                event="suspended",
                action="Доступ партнёра в кабинет приостановлен",
                before=before,
                after=_snapshot(relationship),
                detail=company.name,
            )
    return access_state(company, can_manage=True)
