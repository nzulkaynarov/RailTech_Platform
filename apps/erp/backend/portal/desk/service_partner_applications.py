"""Сервис очереди заявок кандидатов в партнёры (PART-ONBOARD-2, ADR-0022).

Договорной шлюз для отдела снабжения:
- Просмотр очереди заявок с фильтрацией по статусу и подсчётом `pending_count`;
- Сопоставление с существующими контрагентами по ИНН;
- Отправка проекта договора (`contract_sent`);
- Одобрение заявки (`approved`): создание/привязка компании (`parties.Company`),
  активация отношения `partner` с модулями `my_products` и `catalog_requests`,
  фиксация номера и даты договора, связывание с CRM (`PART-CRM`) и отправка приглашения;
- Отклонение заявки (`rejected`) с указанием причины.
"""

from __future__ import annotations

import pghistory
from django.db import transaction
from django.utils import timezone
from integration.services.partner_client import lock_company, request_client_in_crm
from parties.models import (
    Company,
    CompanyRelationship,
    CompanyType,
    Contact,
    PartnerApplication,
    PartnerApplicationSource,
    PartnerApplicationStatus,
    PartnerKind,
    RelationshipRole,
    RelationshipStatus,
    active_contact_q,
)
from portal.desk.service import LANGUAGES, AccessError, _person
from portal.services.invitation import invite_contact
from portal.services.roles import PARTNER_DEFAULT_TOGGLEABLE

from catalog.desk.audit import record

ROLE = RelationshipRole.PARTNER


class _Undo(Exception):
    """Откат при сбое отправки приглашения."""


def _app_dict(app: PartnerApplication) -> dict:
    matching_company_id = app.company_id
    matching_company_name = app.company.name if app.company else None
    if not matching_company_id and app.inn:
        matched = Company.objects.filter(inn=app.inn).first()
        if matched:
            matching_company_id = matched.pk
            matching_company_name = matched.name

    return {
        "id": app.pk,
        "source": app.source,
        "status": app.status,
        "kind": app.kind,
        "company_name": app.company_name,
        "inn": app.inn,
        "contact_name": app.contact_name,
        "email": app.email,
        "phone": app.phone,
        "language": app.language if app.language in LANGUAGES else "ru",
        "categories_description": app.categories_description,
        "contract_number": app.contract_number,
        "contract_date": app.contract_date,
        "rejected_reason": app.rejected_reason,
        "created_at": app.created_at,
        "reviewed_at": app.reviewed_at,
        "matching_company_id": matching_company_id,
        "matching_company_name": matching_company_name,
    }


def list_applications(status_filter: str | None = None) -> dict:
    qs = PartnerApplication.objects.all().select_related("company", "reviewed_by").order_by("-created_at")
    if status_filter:
        qs = qs.filter(status=status_filter)
    pending_count = PartnerApplication.objects.filter(status=PartnerApplicationStatus.SUBMITTED).count()
    return {
        "items": [_app_dict(app) for app in qs],
        "pending_count": pending_count,
    }


def get_application(pk: int) -> dict:
    app = PartnerApplication.objects.filter(pk=pk).select_related("company", "reviewed_by", "applicant_contact").first()
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    data = _app_dict(app)
    data["company_id"] = app.company_id
    data["applicant_contact_id"] = app.applicant_contact_id
    data["reviewed_by"] = _person(app.reviewed_by)
    return data


def send_contract(pk: int, data: dict, user) -> dict:
    with transaction.atomic():
        app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
        if app is None:
            raise AccessError("NOT_FOUND", 404)
        if app.status in (PartnerApplicationStatus.APPROVED, PartnerApplicationStatus.REJECTED):
            raise AccessError("APPLICATION_ALREADY_DECIDED", 400)

        contract_number = (data.get("contract_number") or "").strip()
        contract_date = data.get("contract_date")
        if contract_number:
            app.contract_number = contract_number
        if contract_date:
            app.contract_date = contract_date

        app.status = PartnerApplicationStatus.CONTRACT_SENT
        app.reviewed_by = user
        app.reviewed_at = timezone.now()
        app.save()

        record(
            user,
            entity="partner_application",
            instance=app,
            event="contract_sent",
            action="Проект договора отправлен кандидату",
            before=None,
            after={"status": app.status, "contract_number": app.contract_number},
            detail=app.company_name,
        )
    return get_application(app.pk)


def approve_application(pk: int, data: dict, user) -> dict:
    contract_number = (data.get("contract_number") or "").strip()
    if not contract_number:
        raise AccessError("CONTRACT_NUMBER_REQUIRED", 400)
    contract_date = data.get("contract_date")
    kind = data.get("kind") or ""
    company_id = data.get("company_id")

    try:
        with transaction.atomic(), pghistory.context(user=getattr(user, "pk", None), source="partner_application"):
            app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
            if app is None:
                raise AccessError("NOT_FOUND", 404)
            if app.status == PartnerApplicationStatus.APPROVED:
                raise AccessError("APPLICATION_ALREADY_APPROVED", 400)
            if app.status == PartnerApplicationStatus.REJECTED:
                raise AccessError("APPLICATION_ALREADY_DECIDED", 400)

            # 1. Поиск или создание компании
            company = None
            if company_id:
                company = Company.objects.filter(pk=company_id).first()
                if company is None:
                    raise AccessError("COMPANY_NOT_FOUND", 404)
            elif app.company:
                company = app.company
            elif app.inn:
                company = Company.objects.filter(inn=app.inn).first()

            target_kind = kind if kind in PartnerKind.values else app.kind

            if company is None:
                company = Company.objects.create(
                    name=app.company_name,
                    inn=app.inn,
                    is_active=True,
                )
                supplier_type = CompanyType.objects.filter(code="SUPPLIER").first()
                if supplier_type:
                    company.types.add(supplier_type)
                if target_kind == PartnerKind.MANUFACTURER:
                    manuf_type = CompanyType.objects.filter(code="MANUFACTURER").first()
                    if manuf_type:
                        company.types.add(manuf_type)

            lock_company(company.pk)

            # 2. Поиск или создание контакта
            contact = None
            if app.applicant_contact and app.applicant_contact.company_id == company.pk:
                contact = app.applicant_contact
            else:
                contact = Contact.objects.filter(active_contact_q(), company=company, email__iexact=app.email).first()
                if contact is None:
                    contact = Contact.objects.create(
                        company=company,
                        name=app.contact_name,
                        email=app.email.lower().strip(),
                        phone=app.phone or "",
                        language=app.language if app.language in LANGUAGES else "ru",
                        can_act=True,
                        preferred_channel="email",
                        created_by=user,
                    )

            # 3. Отношение партнёра
            now = timezone.now()
            rel = CompanyRelationship.objects.select_for_update().filter(company=company, role=ROLE).first()
            if rel is None:
                rel = CompanyRelationship(
                    company=company,
                    role=ROLE,
                    kind=target_kind,
                    responsible=user,
                    invited_by=user,
                    invited_at=now,
                    modules=list(PARTNER_DEFAULT_TOGGLEABLE),
                    contract_number=contract_number,
                    contract_date=contract_date,
                    status=(
                        RelationshipStatus.ACTIVE
                        if app.source == PartnerApplicationSource.CLIENT_CABINET
                        else RelationshipStatus.INVITED
                    ),
                )
                if app.source == PartnerApplicationSource.CLIENT_CABINET:
                    rel.activated_at = now
                rel.save()
            else:
                rel.kind = target_kind
                rel.contract_number = contract_number
                rel.contract_date = contract_date
                rel.invited_by = user
                rel.invited_at = now
                rel.suspended_at = None
                if app.source == PartnerApplicationSource.CLIENT_CABINET or rel.activated_at:
                    rel.status = RelationshipStatus.ACTIVE
                    if not rel.activated_at:
                        rel.activated_at = now
                else:
                    rel.status = RelationshipStatus.INVITED
                rel.save()

            # 4. Приглашение и интеграция с CRM
            if app.source != PartnerApplicationSource.CLIENT_CABINET:
                outcome = invite_contact(contact, actor=user, channel="email", language=contact.language)
                if outcome.error:
                    raise _Undo(outcome.error)

            request_client_in_crm(company, user)

            # 5. Завершение заявки
            app.company = company
            app.status = PartnerApplicationStatus.APPROVED
            app.contract_number = contract_number
            app.contract_date = contract_date
            app.reviewed_by = user
            app.reviewed_at = now
            app.save()

            record(
                user,
                entity="partner_application",
                instance=app,
                event="approved",
                action="Заявка кандидата в партнёры одобрена",
                before=None,
                after={"status": app.status, "company": company.pk, "contract_number": contract_number},
                detail=app.company_name,
            )
    except _Undo as undo:
        code = str(undo)
        raise AccessError(code) from None

    return get_application(app.pk)


def reject_application(pk: int, data: dict, user) -> dict:
    rejected_reason = (data.get("rejected_reason") or "").strip()
    if not rejected_reason:
        raise AccessError("REJECTED_REASON_REQUIRED", 400)

    with transaction.atomic():
        app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
        if app is None:
            raise AccessError("NOT_FOUND", 404)
        if app.status in (PartnerApplicationStatus.APPROVED, PartnerApplicationStatus.REJECTED):
            raise AccessError("APPLICATION_ALREADY_DECIDED", 400)

        app.status = PartnerApplicationStatus.REJECTED
        app.rejected_reason = rejected_reason
        app.reviewed_by = user
        app.reviewed_at = timezone.now()
        app.save()

        record(
            user,
            entity="partner_application",
            instance=app,
            event="rejected",
            action="Заявка кандидата в партнёры отклонена",
            before=None,
            after={"status": app.status, "rejected_reason": rejected_reason},
            detail=app.company_name,
        )
    return get_application(app.pk)
