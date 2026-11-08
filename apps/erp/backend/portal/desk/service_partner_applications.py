"""Сервис очереди заявок кандидатов в партнёры (PART-ONBOARD-2, ADR-0022; шлюз — FX-1).

Договорной шлюз для отдела снабжения:
- Просмотр очереди заявок с фильтрацией по статусу и подсчётом `pending_count`;
- Сопоставление с существующими контрагентами по ИНН или рег. номеру. Совпадение — предложение человеку, не автопривязка
  (правило PART-CRM, DECISIONS 2026-11-04): ИНН анкеты никем не проверен, а привязка даёт контакту вход и `can_act` в чужой
  компании. Пока сотрудник не выбрал `company_id` или `create_new_company`, ни отправка договора, ни одобрение не проходят;
- Отправка проекта договора (`contract_sent`);
- Одобрение заявки (`approved`): только после согласия кандидата (`candidate_agreed`) либо явным обходом с причиной в журнале;
  создание/привязка компании (`parties.Company`), активация отношения `partner` с модулями `my_products` и
  `catalog_requests`, фиксация номера и даты договора, связывание с CRM (`PART-CRM`) и отправка приглашения;
- Отклонение заявки (`rejected`) с указанием причины; временный вход кандидата закрывается.
"""

from __future__ import annotations

import pghistory
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from integration.models import CrmContactMapping
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
from portal.services.partner_contract import PartnerContractRenderError
from portal.services.roles import PARTNER_DEFAULT_TOGGLEABLE

from catalog.desk.audit import record
from core.models.notifications import EmailLog

ROLE = RelationshipRole.PARTNER
INVITE_TEMPLATE = "portal_invitation"
INN_MAX_LENGTH = Company._meta.get_field("inn").max_length


class _Undo(Exception):
    """Откат при сбое отправки приглашения."""


def _company_match(app: PartnerApplication) -> tuple[str | None, Company | None]:
    """Существующая компания с ключом заявки и основание: ИНН, затем пара «страна + рег. номер»."""
    if app.inn:
        matched = Company.objects.filter(inn=app.inn).first()
        if matched:
            return "inn", matched
    if app.registration_number:
        matched = Company.objects.filter(
            registration_number__iexact=app.registration_number,
            country=app.country,
        ).first()
        if matched:
            return "registration_number", matched
    return None, None


def _chosen_company(app: PartnerApplication, data: dict) -> Company | None:
    """Компания заявки по решению сотрудника; `None` — завести новую. Совпадение без решения — отказ (FX-1, PART-CRM)."""
    company_id = data.get("company_id")
    if company_id and app.company_id and company_id != app.company_id:
        # Привязка решена при отправке договора: иначе первая компания осталась бы с приглашением и открытым входом
        raise AccessError("COMPANY_MISMATCH")
    if company_id:
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise AccessError("COMPANY_NOT_FOUND", 404)
        return company
    if app.company_id:
        return app.company
    basis, matched = _company_match(app)
    if matched is None:
        return None
    if not data.get("create_new_company"):
        raise AccessError("COMPANY_MATCH_CONFIRMATION_REQUIRED")
    if basis == "inn":  # ИНН уникален: «другая компания с тем же ИНН» — опечатка заявки, отклоняется с причиной
        raise AccessError("COMPANY_INN_TAKEN")
    return None


def _create_company(app: PartnerApplication, kind: str) -> Company:
    company_inn = app.inn.strip() if app.inn else None
    company_reg = app.registration_number.strip() if app.registration_number else ""
    # Если передан не-UZ и указан только ИНН — считаем рег. номером
    if app.country and app.country.code != "UZ" and company_inn and not company_reg:
        company_reg = company_inn
        company_inn = None
    if company_inn and len(company_inn) > INN_MAX_LENGTH:
        raise AccessError("INN_TOO_LONG")

    company = Company.objects.create(
        name=app.company_name,
        country=app.country,
        inn=company_inn,
        registration_number=company_reg,
        is_active=True,
    )
    supplier_type = CompanyType.objects.filter(code="SUPPLIER").first()
    if supplier_type:
        company.types.add(supplier_type)
    if kind == PartnerKind.MANUFACTURER:
        manuf_type = CompanyType.objects.filter(code="MANUFACTURER").first()
        if manuf_type:
            company.types.add(manuf_type)
    return company


def _applicant_contact(app: PartnerApplication, company: Company, user) -> Contact:
    if app.applicant_contact and app.applicant_contact.company_id == company.pk:
        return app.applicant_contact
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
        app.applicant_contact_created = True
    return contact


def _render_contract(app: PartnerApplication, **kwargs) -> bytes:
    from portal.services.partner_contract import render_partner_contract_pdf

    try:
        return render_partner_contract_pdf(app, **kwargs)
    except PartnerContractRenderError:
        raise AccessError("CONTRACT_RENDER_FAILED") from None


def _invite_deliveries(apps) -> dict[str, str]:
    """Итог последнего письма-приглашения по адресам заявок: `queued`, `sent`, `failed` (одним запросом)."""
    emails = {app.email.lower() for app in apps if app.source == PartnerApplicationSource.PUBLIC and app.email}
    if not emails:
        return {}
    wanted = Q()
    for email in emails:
        wanted |= Q(to_emails__contains=[email])
    deliveries: dict[str, str] = {}
    logs = EmailLog.objects.filter(wanted, template=INVITE_TEMPLATE).order_by("created_at", "pk")
    for to_emails, status in logs.values_list("to_emails", "status"):
        for email in to_emails:
            if email.lower() in emails:
                deliveries[email.lower()] = status.lower()
    return deliveries


def _app_dict(app: PartnerApplication, deliveries: dict[str, str]) -> dict:
    matching_company_id = app.company_id
    matching_company_name = app.company.name if app.company else None
    company_match_pending = None
    if not matching_company_id:
        company_match_pending, matched = _company_match(app)
        if matched:
            matching_company_id = matched.pk
            matching_company_name = matched.name

    return {
        "id": app.pk,
        "source": app.source,
        "status": app.status,
        "kind": app.kind,
        "company_name": app.company_name,
        "country": app.country.code if app.country else None,
        "country_name": app.country.name if app.country else None,
        "inn": app.inn,
        "registration_number": app.registration_number,
        "contact_name": app.contact_name,
        "email": app.email,
        "phone": app.phone,
        "language": app.language if app.language in LANGUAGES else "ru",
        "categories_description": app.categories_description,
        "contract_number": app.contract_number,
        "contract_date": app.contract_date,
        "contract_draft_sent_at": app.contract_draft_sent_at,
        "candidate_agreed_at": app.candidate_agreed_at,
        "candidate_notes": app.candidate_notes,
        "has_contract_pdf": bool(app.contract_pdf),
        "rejected_reason": app.rejected_reason,
        "created_at": app.created_at,
        "reviewed_at": app.reviewed_at,
        "matching_company_id": matching_company_id,
        "matching_company_name": matching_company_name,
        "company_match_pending": company_match_pending,
        "invite_delivery": deliveries.get(app.email.lower()),
    }


def list_applications(status_filter: str | None = None) -> dict:
    qs = PartnerApplication.objects.all().select_related("company", "reviewed_by").order_by("-created_at")
    if status_filter:
        qs = qs.filter(status=status_filter)
    # Ждут сотрудника: новые и согласованные кандидатом
    pending_count = PartnerApplication.objects.filter(
        status__in=[PartnerApplicationStatus.SUBMITTED, PartnerApplicationStatus.CANDIDATE_AGREED]
    ).count()
    apps = list(qs)
    deliveries = _invite_deliveries(apps)
    return {
        "items": [_app_dict(app, deliveries) for app in apps],
        "pending_count": pending_count,
    }


def get_application(pk: int) -> dict:
    app = PartnerApplication.objects.filter(pk=pk).select_related("company", "reviewed_by", "applicant_contact").first()
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    data = _app_dict(app, _invite_deliveries([app]))
    data["company_id"] = app.company_id
    data["applicant_contact_id"] = app.applicant_contact_id
    data["reviewed_by"] = _person(app.reviewed_by)
    return data


def send_contract(pk: int, data: dict, user) -> dict:
    from django.core.files.base import ContentFile
    from portal.services.partner_contract import generate_partner_contract_number

    with transaction.atomic():
        app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
        if app is None:
            raise AccessError("NOT_FOUND", 404)
        if app.status in (PartnerApplicationStatus.APPROVED, PartnerApplicationStatus.REJECTED):
            raise AccessError("APPLICATION_ALREADY_DECIDED", 400)

        contract_number = (data.get("contract_number") or "").strip()
        contract_date = data.get("contract_date")
        if not contract_number and not app.contract_number:
            contract_number = generate_partner_contract_number(app.pk)
        if contract_number:
            app.contract_number = contract_number
        if contract_date:
            app.contract_date = contract_date
        elif not app.contract_date:
            app.contract_date = timezone.localdate()

        app.status = PartnerApplicationStatus.CONTRACT_SENT
        app.contract_draft_sent_at = timezone.now()
        app.candidate_agreed_at = None  # договор отправлен заново — прежнее согласие к нему не относится
        app.reviewed_by = user
        app.reviewed_at = timezone.now()

        invited_contact = None
        # Заявка из внешнего входа: кандидату нужен вход, чтобы прочитать и согласовать договор
        if app.source == PartnerApplicationSource.PUBLIC:
            if not app.company_id:
                company = _chosen_company(app, data) or _create_company(app, app.kind)
                contact = _applicant_contact(app, company, user)
                app.company = company
                app.applicant_contact = contact

                # Создаём отношение с INVITED и пустыми модулями (только вход в ЛК для согласования)
                rel = CompanyRelationship.objects.filter(company=company, role=ROLE).first()
                if rel is None:
                    rel = CompanyRelationship.objects.create(
                        company=company,
                        role=ROLE,
                        kind=app.kind,
                        responsible=user,
                        invited_by=user,
                        invited_at=timezone.now(),
                        modules=[],
                        contract_number=app.contract_number,
                        contract_date=app.contract_date,
                        status=RelationshipStatus.INVITED,
                    )
                elif rel.status == RelationshipStatus.SUSPENDED:
                    raise AccessError("PARTNER_SUSPENDED")
                elif rel.status == RelationshipStatus.INVITED:
                    # Действующему партнёру договор меняет только одобрение: кандидат ещё ничего не согласовал
                    rel.contract_number = app.contract_number
                    rel.contract_date = app.contract_date
                    rel.save(update_fields=["contract_number", "contract_date"])
            invited_contact = app.applicant_contact

        # Сначала договор: при сбое рендера ни заглушки, ни письма со ссылкой на договор
        pdf_bytes = _render_contract(app, draft=True)

        if invited_contact is not None:
            # Письмо со ссылкой для входа; не ушло — вся операция откатывается, сотрудник видит причину (FX-1)
            outcome = invite_contact(invited_contact, actor=user, channel="email", language=invited_contact.language)
            if outcome.error:
                raise AccessError(outcome.error)

        pdf_filename = f"Partner_Contract_{app.contract_number or app.pk}_draft.pdf"
        app.contract_pdf.save(pdf_filename, ContentFile(pdf_bytes), save=False)
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
    kind = data.get("kind") or ""
    override_reason = (data.get("override_reason") or "").strip()

    try:
        with transaction.atomic(), pghistory.context(user=getattr(user, "pk", None), source="partner_application"):
            app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
            if app is None:
                raise AccessError("NOT_FOUND", 404)
            if app.status == PartnerApplicationStatus.APPROVED:
                raise AccessError("APPLICATION_ALREADY_APPROVED", 400)
            if app.status == PartnerApplicationStatus.REJECTED:
                raise AccessError("APPLICATION_ALREADY_DECIDED", 400)
            # Без согласия кандидата — только явный обход с причиной в журнале и только после отправки договора (FX-1)
            bypassed_agreement = app.status != PartnerApplicationStatus.CANDIDATE_AGREED
            may_bypass = app.status == PartnerApplicationStatus.CONTRACT_SENT and override_reason
            if bypassed_agreement and not may_bypass:
                raise AccessError("CANDIDATE_AGREEMENT_REQUIRED", 400)

            # 1. Компания: выбранная сотрудником, уже привязанная или новая
            target_kind = kind if kind in PartnerKind.values else app.kind
            company = _chosen_company(app, data) or _create_company(app, target_kind)

            lock_company(company.pk)

            # 2. Поиск или создание контакта
            contact = _applicant_contact(app, company, user)

            # 3. Отношение партнёра
            now = timezone.now()
            rel = CompanyRelationship.objects.select_for_update().filter(company=company, role=ROLE).first()
            if rel is not None and rel.status == RelationshipStatus.SUSPENDED:
                # Приостановку снимает только решение в карточке поставщика, не одобрение заявки (FX-1)
                raise AccessError("PARTNER_SUSPENDED")
            contract_date = (
                data.get("contract_date")
                or app.contract_date
                or (rel.contract_date if rel else None)
                or timezone.localdate()
            )
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
                if rel.status == RelationshipStatus.INVITED:
                    rel.invited_by = user
                    rel.invited_at = now
                    # Пустые модули — временный вход кандидата; настроенные сотрудником не перезаписываем (FX-1)
                    if not rel.modules:
                        rel.modules = list(PARTNER_DEFAULT_TOGGLEABLE)
                rel.kind = target_kind
                rel.contract_number = contract_number
                rel.contract_date = contract_date
                rel.status = RelationshipStatus.ACTIVE
                if not rel.activated_at:
                    rel.activated_at = now
                rel.save()

            # 4. Завершение заявки и рендер договора: при сбое рендера заявка не одобрена и письма нет
            app.company = company
            app.applicant_contact = contact
            app.status = PartnerApplicationStatus.APPROVED
            app.contract_number = contract_number
            app.contract_date = contract_date
            app.reviewed_by = user
            app.reviewed_at = now

            from django.core.files.base import ContentFile

            signed_pdf = _render_contract(app, draft=False, director_user=user)

            # 5. Приглашение и интеграция с CRM
            if app.source != PartnerApplicationSource.CLIENT_CABINET and not contact.last_login_at:
                outcome = invite_contact(contact, actor=user, channel="email", language=contact.language)
                if outcome.error and "ALREADY" not in outcome.error:
                    raise _Undo(outcome.error)

            request_client_in_crm(company, user)

            pdf_filename = f"Partner_Contract_{contract_number}_signed.pdf"
            app.contract_pdf.save(pdf_filename, ContentFile(signed_pdf), save=False)
            app.save()

            after = {"status": app.status, "company": company.pk, "contract_number": contract_number}
            if bypassed_agreement:
                record(
                    user,
                    entity="partner_application",
                    instance=app,
                    event="approved_without_agreement",
                    action="Заявка кандидата в партнёры одобрена без согласия кандидата",
                    before=None,
                    after={**after, "override_reason": override_reason},
                    detail=app.company_name,
                    level="WARNING",
                )
            else:
                record(
                    user,
                    entity="partner_application",
                    instance=app,
                    event="approved",
                    action="Заявка кандидата в партнёры одобрена",
                    before=None,
                    after=after,
                    detail=app.company_name,
                )
    except _Undo as undo:
        code = str(undo)
        raise AccessError(code) from None

    return get_application(app.pk)


def _close_candidate_access(app: PartnerApplication) -> None:
    """Отклонённый кандидат не становится партнёром первым входом (FX-1): временный вход снимается, приглашённое сотрудником
    отношение приостанавливается. Действующего партнёра отклонение новой заявки не меняет."""
    if not app.company_id:
        return
    invited = CompanyRelationship.objects.filter(
        company_id=app.company_id, role=ROLE, status=RelationshipStatus.INVITED
    )
    invited.filter(modules=[]).delete()
    invited.update(status=RelationshipStatus.SUSPENDED, suspended_at=timezone.now())
    _archive_created_contact(app)


def _archive_created_contact(app: PartnerApplication) -> None:
    """Контакт, заведённый этой заявкой, снимается (решение архитектора, #427): вход читает `active_contact_q`.

    Существующий контакт компании не трогаем, как и связанный с CRM или с другой неотклонённой заявкой.
    """
    contact = app.applicant_contact
    if contact is None or not app.applicant_contact_created or contact.is_archived:
        return
    other_application = PartnerApplication.objects.filter(applicant_contact=contact).exclude(pk=app.pk)
    if other_application.exclude(status=PartnerApplicationStatus.REJECTED).exists():
        return
    if CrmContactMapping.objects.filter(contact=contact).exists():
        return
    contact.archived_at = timezone.now()
    contact.save(update_fields=["archived_at"])


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
        _close_candidate_access(app)

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
