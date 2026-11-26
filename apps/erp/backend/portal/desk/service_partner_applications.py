"""Сервис очереди заявок кандидатов в партнёры (PART-ONBOARD-2, ADR-0022; шлюз — FX-1).

Договорной шлюз для отдела снабжения:
- Просмотр очереди заявок с фильтрацией по статусу и подсчётом `pending_count`;
- Сопоставление с существующими контрагентами по ИНН или рег. номеру. Совпадение — предложение человеку, не автопривязка
  (правило PART-CRM, DECISIONS 2026-11-04): ИНН анкеты никем не проверен, а привязка даёт контакту вход и `can_act` в чужой
  компании. Пока сотрудник не выбрал `company_id` или `create_new_company`, ни отправка договора, ни одобрение не проходят;
- Подготовка договора (`service_partner_contract`: утверждённый шаблон либо свой файл, согласование держателем «Право»)
  и его отправка кандидату (`contract_sent`): кандидат получает вход в кабинет при любом источнике заявки (ПД-1);
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
from parties.company_admin import ensure_company_admin
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
from portal.desk import service_partner_contract as contract_step
from portal.desk.service import LANGUAGES, AccessError, _person
from portal.services.invitation import invite_contact
from portal.services.roles import PARTNER_DEFAULT_TOGGLEABLE

from catalog.desk.audit import record
from core.models import Country
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
    # Пустая почта не сопоставляет контакт: иначе заявка без почты «нашла» бы любой контакт без адреса
    contact = (
        Contact.objects.filter(active_contact_q(), company=company, email__iexact=app.email).first()
        if app.email.strip()
        else None
    )
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
    ensure_company_admin(company)
    contact.refresh_from_db()
    return contact


def _invite_deliveries(apps) -> dict[str, str]:
    """Итог последнего письма-приглашения по адресам заявок: `queued`, `sent`, `failed` (одним запросом)."""
    emails = {app.email.lower() for app in apps if app.source != PartnerApplicationSource.CLIENT_CABINET and app.email}
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


def _app_dict(app: PartnerApplication, deliveries: dict[str, str], viewer=None) -> dict:
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
        # Перечень `source` в контракте ERP не растёт (ломающее после 1.0): лид отдаётся как письмо с признаком
        "source": PartnerApplicationSource.LETTER if app.source == PartnerApplicationSource.LEAD else app.source,
        "from_lead": app.source == PartnerApplicationSource.LEAD,
        "status": app.status,
        "source_ref": app.source_ref,
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
        "has_contract_pdf": bool(contract_step.current_document(app)),
        **contract_step.contract_facts(app, viewer=viewer),
        "rejected_reason": app.rejected_reason,
        "created_at": app.created_at,
        "reviewed_at": app.reviewed_at,
        "matching_company_id": matching_company_id,
        "matching_company_name": matching_company_name,
        "company_match_pending": company_match_pending,
        "invite_delivery": deliveries.get(app.email.lower()),
    }


def list_applications(status_filter: str | None = None, viewer=None) -> dict:
    qs = (
        PartnerApplication.objects.all()
        .select_related(
            "company",
            "reviewed_by",
            "contract_template",
            "contract_approval_requested_by",
            "contract_approval_decided_by",
        )
        .prefetch_related("package_documents")
        .order_by("-created_at")
    )
    if status_filter:
        qs = qs.filter(status=status_filter)
    # Ждут сотрудника: новые и согласованные кандидатом
    pending_count = PartnerApplication.objects.filter(
        status__in=[PartnerApplicationStatus.SUBMITTED, PartnerApplicationStatus.CANDIDATE_AGREED]
    ).count()
    apps = list(qs)
    deliveries = _invite_deliveries(apps)
    return {
        "items": [_app_dict(app, deliveries, viewer) for app in apps],
        "pending_count": pending_count,
    }


@transaction.atomic
def create_from_letter(data: dict, user) -> dict:
    """«Передать в работу» по входящему письму (план 1.9): сотрудник заводит заявку кандидата сам.

    Согласия кандидата на обработку данных ещё нет (`consent=False`): дальше — тот же договорный шлюз, кандидат
    соглашается с проектом договора; одобрение без согласия — только с причиной в журнале (FX-1)."""
    country_code = (data.get("country") or "UZ").strip().upper()
    app = PartnerApplication.objects.create(
        source=PartnerApplicationSource.LETTER,
        source_ref=data["source_ref"].strip(),
        country=Country.objects.filter(code__iexact=country_code).first(),
        company_name=data["company_name"].strip(),
        inn=(data.get("inn") or "").strip(),
        kind=data.get("kind") or "supplier",
        categories_description=data["categories_description"].strip(),
        contact_name=data["contact_name"].strip(),
        email=data["email"].strip().lower(),
        phone=(data.get("phone") or "").strip(),
        language=data.get("language") or "ru",
        consent=False,
        status=PartnerApplicationStatus.SUBMITTED,
    )
    record(
        user,
        entity="partner_application",
        instance=app,
        event="created_from_letter",
        action=f"Заявка заведена по письму {app.source_ref}",
        before=None,
        after={"status": app.status, "source_ref": app.source_ref},
        detail=app.company_name,
    )
    return get_application(app.pk, user)


@transaction.atomic
def create_from_lead(data: dict) -> tuple[PartnerApplication, bool]:
    """«Партнёр» из карточки лида CRM (ЛП-1): заявка кандидата по лиду, `source = lead`, `source_ref` — номер лида.

    Идемпотентно по номеру лида: повтор и параллельный повтор (блокировка на номер) возвращают ту же заявку без второй
    строки в очереди. Отклонённая заявка не блокирует: тот же лид можно подать снова. Согласия кандидата ещё нет
    (`consent=False`) — дальше обычный договорный шлюз; компания заводится при одобрении, а не здесь."""
    from integration.services.handoff import _advisory_lock

    ref = data["source_ref"].strip()
    _advisory_lock("partner-lead", ref)
    existing = (
        PartnerApplication.objects.filter(source=PartnerApplicationSource.LEAD, source_ref=ref)
        .exclude(status=PartnerApplicationStatus.REJECTED)
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return existing, False
    country_code = (data.get("country") or "UZ").strip().upper()
    app = PartnerApplication.objects.create(
        source=PartnerApplicationSource.LEAD,
        source_ref=ref,
        country=Country.objects.filter(code__iexact=country_code).first(),
        company_name=data["company_name"].strip(),
        inn=(data.get("inn") or "").strip(),
        kind=data.get("kind") or "supplier",
        categories_description=data["categories_description"].strip(),
        contact_name=data["contact_name"].strip(),
        email=(data.get("email") or "").strip().lower(),
        phone=(data.get("phone") or "").strip(),
        language=data.get("language") or "ru",
        consent=False,
        status=PartnerApplicationStatus.SUBMITTED,
    )
    record(
        None,
        entity="partner_application",
        instance=app,
        event="created_from_lead",
        action=f"Заявка заведена по лиду {app.source_ref}",
        before=None,
        after={"status": app.status, "source_ref": app.source_ref},
        detail=app.company_name,
    )
    return app, True


def get_application(pk: int, viewer=None) -> dict:
    app = (
        PartnerApplication.objects.filter(pk=pk)
        .select_related(
            "company",
            "reviewed_by",
            "applicant_contact",
            "contract_template",
            "contract_approval_requested_by",
            "contract_approval_decided_by",
        )
        .first()
    )
    if app is None:
        raise AccessError("NOT_FOUND", 404)
    data = _app_dict(app, _invite_deliveries([app]), viewer)
    data["company_id"] = app.company_id
    data["applicant_contact_id"] = app.applicant_contact_id
    data["reviewed_by"] = _person(app.reviewed_by)
    return data


def send_contract(pk: int, data: dict, user) -> dict:
    """Отправка подготовленного договора кандидату (ПД-1): нечего отправлять или он ждёт решения «Право» — отказ с причиной.

    Кандидат получает вход в кабинет при любом источнике заявки, кроме кабинета клиента (там он уже внутри): компания и
    контакт заводятся или привязываются по решению сотрудника, письмо уходит на языке контакта."""
    with transaction.atomic():
        app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
        if app is None:
            raise AccessError("NOT_FOUND", 404)
        if app.status in (PartnerApplicationStatus.APPROVED, PartnerApplicationStatus.REJECTED):
            raise AccessError("APPLICATION_ALREADY_DECIDED", 400)
        if data.get("company_id") and app.company_id and data["company_id"] != app.company_id:
            raise AccessError(
                "COMPANY_MISMATCH"
            )  # привязка решена: молча игнорировать выбор сотрудника нельзя (B-FX1-1)
        blocker = contract_step.send_blocker(app)
        if blocker:
            raise AccessError(blocker)

        invited_contact = None
        # Кандидату нужен вход, чтобы прочитать и согласовать договор; из кабинета клиента он уже вошёл
        # ПК-1: путь не останавливается на отсутствии почты — компания и контакт заводятся, приглашение в Кабинет уходит
        # позже (`invite_candidate`), когда адрес появится; сотрудник видит это в карточке.
        if app.source != PartnerApplicationSource.CLIENT_CABINET:
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
            invited_contact = app.applicant_contact if (app.email or "").strip() else None

        app.status = PartnerApplicationStatus.CONTRACT_SENT
        app.contract_draft_sent_at = timezone.now()
        app.candidate_agreed_at = None  # договор отправлен заново — прежнее согласие к нему не относится
        app.candidate_returned_at = None
        app.package_documents.update(candidate_remark="")  # замечания учтены в отправляемой редакции
        app.reviewed_by = user
        app.reviewed_at = timezone.now()

        if invited_contact is not None:
            # Письмо со ссылкой для входа; не ушло — вся операция откатывается, сотрудник видит причину (FX-1)
            outcome = invite_contact(invited_contact, actor=user, channel="email", language=invited_contact.language)
            if outcome.error:
                raise AccessError(outcome.error)
        app.save()

        record(
            user,
            entity="partner_application",
            instance=app,
            event="contract_sent",
            action="Договор отправлен кандидату",
            before=None,
            after={"status": app.status, "contract_number": app.contract_number, "source": app.contract_source},
            detail=app.company_name,
        )
    return get_application(app.pk, user)


def invite_candidate(pk: int, data: dict, user) -> dict:
    """«Пригласить в Кабинет» позже (ПК-1): почты не было, когда договор отправили, — теперь она есть.

    Адрес из запроса записывается в заявку и контакт кандидата; приглашение уходит письмом. Договор в Кабинете кандидат
    увидит после входа."""
    email = (data.get("email") or "").strip().lower()
    with transaction.atomic():
        app = PartnerApplication.objects.select_for_update().filter(pk=pk).first()
        if app is None:
            raise AccessError("NOT_FOUND", 404)
        if app.status in (PartnerApplicationStatus.APPROVED, PartnerApplicationStatus.REJECTED):
            raise AccessError("APPLICATION_ALREADY_DECIDED", 400)
        contact = app.applicant_contact
        if contact is None or not app.company_id:
            raise AccessError("CONTRACT_NOT_SENT", 400)
        email = email or (app.email or "").strip().lower()
        if not email:
            raise AccessError("CANDIDATE_EMAIL_REQUIRED", 400)
        app.email = email
        app.save(update_fields=["email", "updated_at"])
        if (contact.email or "").strip().lower() != email:
            contact.email = email
            contact.save(update_fields=["email"])
        outcome = invite_contact(contact, actor=user, channel="email", language=contact.language)
        if outcome.error:
            raise AccessError(outcome.error)
        record(
            user,
            entity="partner_application",
            instance=app,
            event="candidate_invited",
            action="Кандидат приглашён в Кабинет",
            before=None,
            after={"email_set": True},
            detail=app.company_name,
        )
    return get_application(app.pk, user)


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

            # ПК-1: «Отметить: подписан» — скан ИЛИ заметка (скан не обязателен); договор подготовлен в системе
            signed_note = (data.get("signed_note") or "").strip()[:1000]
            if app.contract_source and not app.signed_scan and not (signed_note or override_reason):
                raise AccessError("SIGNED_PROOF_REQUIRED", 400)

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

            # 4. Завершение заявки
            app.company = company
            app.applicant_contact = contact
            app.status = PartnerApplicationStatus.APPROVED
            app.contract_number = contract_number
            app.contract_date = contract_date
            app.reviewed_by = user
            app.reviewed_at = now
            app.signed_note = signed_note
            app.signed_marked_at = now
            # Срок договора считается в момент отметки по правилу компании (ДС-1, тот же сервис, что у клиентов)
            from crm.services.contract_term import apply_to_package, apply_to_partner_application

            apply_to_partner_application(app, signed_on=timezone.localdate())
            apply_to_package(app, signed_on=timezone.localdate())

            # 5. Приглашение и интеграция с CRM
            if (
                app.source != PartnerApplicationSource.CLIENT_CABINET
                and not contact.last_login_at
                and (contact.email or "").strip()
            ):
                outcome = invite_contact(contact, actor=user, channel="email", language=contact.language)
                if outcome.error and "ALREADY" not in outcome.error:
                    raise _Undo(outcome.error)

            request_client_in_crm(company, user)

            app.save()

            after = {"status": app.status, "company": company.pk, "contract_number": contract_number}
            if signed_note:
                after["signed_note"] = signed_note
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

    return get_application(app.pk, user)


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
    contact.can_act = False
    contact.is_admin = False
    contact.save(update_fields=["archived_at", "can_act", "is_admin"])


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
    return get_application(app.pk, user)
