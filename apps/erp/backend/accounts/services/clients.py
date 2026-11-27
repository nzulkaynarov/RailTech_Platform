"""Seller-managed (offline) clients — the CRM client base.

World-standard Account(Company)+Contact: a seller records a client they reached through
other channels (no self-registration), then builds a КП for it. Search-before-create
de-dup avoids duplicate accounts (the #1 CRM pitfall). See
Docs/old/specs/client-base-design-2026-06-24.md.
"""

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Value
from django.db.models.functions import Coalesce
from parties.company_admin import ensure_company_admin
from parties.models import active_company_q

from ..constants import CompanyTypeCode
from ..models import Company, CompanyType, Contact, CustomUser

logger = logging.getLogger(__name__)


def _seller_company_ids(user: CustomUser) -> list:
    """`[own_company_id]` for own-company staff (the single seller), else empty."""
    from .permissions import primary_seller_company_id

    company_id = primary_seller_company_id(user)
    return [company_id] if company_id else []


def client_book_q() -> Q:
    """A company is a client of the own company by facts (СЦ-12): CLIENT type, a CRM client mapping
    (verified or linked by TIN) or a deal with it.

    Who created a contact is not a signal: a supplier's contact made by staff does not make a client,
    and CRM clients arrive with contacts that have no author. Subqueries, not JOINs — rows are not
    multiplied (as in `portal.services.access`).

    КОНТР-1б: once an employee removed the client role («Не клиент», `Company.client_role_removed_at`), the CRM
    mapping stops counting and only deals created AFTER that moment do; requests hidden as «created by mistake»
    never count. The CLIENT type is read as is — whoever sets it again makes the company a client again.
    """
    from integration.models import CrmClientMapping
    from sales.models import Deal

    pk = OuterRef("pk")
    never = Value(datetime(1970, 1, 1, tzinfo=dt_timezone.utc))
    return (
        Q(Exists(Company.types.through.objects.filter(company_id=pk, companytype__code=CompanyTypeCode.CLIENT)))
        | (Q(Exists(CrmClientMapping.objects.filter(company_id=pk))) & Q(client_role_removed_at__isnull=True))
        | Q(
            Exists(
                Deal.objects.filter(company_id=pk, hidden_in_lists=False).filter(
                    created_at__gt=Coalesce(OuterRef("client_role_removed_at"), never)
                )
            )
        )
    )


def seller_clients(user: CustomUser):
    """The own company's client book (team-level, `client_book_q`); the own company is never in it.
    Non-staff get an empty book."""
    seller_ids = _seller_company_ids(user)
    if not seller_ids:
        return Company.objects.none()
    return Company.objects.filter(client_book_q()).exclude(pk__in=seller_ids).order_by("name")


def find_client_company(user: CustomUser, *, inn: str = "", name: str = "") -> Optional[Company]:
    """Search-before-create (СЦ-12, ADR-0028 — one company in all roles).

    TIN is a strong key: any active company except the own one, by `inn` or `stated_inn` (a supplier
    recorded as a client is reused, not duplicated). Name is a weak key: within the client book only."""
    seller_ids = _seller_company_ids(user)
    if not seller_ids:
        return None
    if inn:
        match = (
            Company.objects.filter(active_company_q(), Q(inn=inn) | Q(stated_inn=inn))
            .exclude(pk__in=seller_ids)
            .order_by("pk")
            .first()
        )
        if match:
            return match
    if name:
        return seller_clients(user).filter(name__iexact=name.strip()).first()
    return None


@transaction.atomic
def create_offline_client(
    *,
    seller: CustomUser,
    company_name: str,
    contact_name: str,
    inn: str = "",
    email: str = "",
    phone: str = "",
    position: str = "",
    can_act: bool = True,  # сотрудник сам заводит клиента и решает, может ли контакт подписывать (как в продукте)
    language: str = "ru",
    preferred_channel: str = "email",
    telegram_username: str = "",
) -> Tuple[Optional[dict], Optional[str]]:
    """Create (or reuse) an offline client company + its primary contact.

    Returns ({"company", "contact", "company_created"}, None) or (None, error_code).
    A contact needs at least an email OR a phone (world-practice reachability rule).
    """
    company_name = (company_name or "").strip()
    contact_name = (contact_name or "").strip()
    inn = (inn or "").strip()
    email = (email or "").strip()
    phone = (phone or "").strip()
    telegram_username = (telegram_username or "").strip().lstrip("@")
    # Client books belong to seller teams; a non-seller would create an orphan company
    # invisible even to themselves (seller_clients scoping) — refuse instead.
    if not _seller_company_ids(seller):
        return None, "ONLY_SELLER_CAN_CREATE_CLIENTS"
    if not company_name or not contact_name:
        return None, "CLIENT_FIELDS_REQUIRED"
    if not (email or phone):
        return None, "CONTACT_NEEDS_EMAIL_OR_PHONE"

    # Search-before-create (СЦ-12): TIN across known companies, name within the book.
    company = find_client_company(seller, inn=inn, name=company_name)
    company_created = company is None
    if company_created:
        company = Company.objects.create(
            name=company_name,
            stated_inn=inn,  # NOT the unique `inn` — cross-tenant dups allowed
            is_registered=False,  # rep-created, no platform login yet
        )
    # Staff records this company as a client: CLIENT for a new and for a reused company (a supplier turned
    # client) — otherwise a reused company stays out of the book and its deal is refused.
    client_type, _ = CompanyType.objects.get_or_create(code=CompanyTypeCode.CLIENT, defaults={"name": "Клиент"})
    company.types.add(client_type)

    # Reuse a contact with the same email; else create. First contact becomes primary.
    contact = None
    if email:
        contact = company.contacts.filter(email__iexact=email).first()
    if contact is None:
        contact = Contact.objects.create(
            company=company,
            name=contact_name,
            email=email,
            phone=phone,
            position=position,
            is_primary=not company.contacts.filter(is_primary=True).exists(),
            created_by=seller,
            can_act=can_act,
            language=language if language in ("ru", "uz", "en") else "ru",
            preferred_channel=preferred_channel if preferred_channel in ("email", "telegram", "both") else "email",
            telegram_username=telegram_username,
        )
    ensure_company_admin(company)
    contact.refresh_from_db()

    return {"company": company, "contact": contact, "company_created": company_created}, None
