"""Seller-managed (offline) clients — the CRM client base.

World-standard Account(Company)+Contact: a seller records a client they reached through
other channels (no self-registration), then builds a КП for it. Search-before-create
de-dup avoids duplicate accounts (the #1 CRM pitfall). See
Docs/old/specs/client-base-design-2026-06-24.md.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction

from ..models import Company, CompanyType, Contact, CustomUser

logger = logging.getLogger(__name__)


def _seller_company_ids(user: CustomUser) -> list:
    """`[own_company_id]` for own-company staff (the single seller), else empty."""
    from .permissions import primary_seller_company_id

    company_id = primary_seller_company_id(user)
    return [company_id] if company_id else []


def seller_clients(user: CustomUser):
    """The own company's client base (team-level): companies its staff created as offline
    clients (via a Contact). Non-staff get an empty book.
    """
    seller_ids = _seller_company_ids(user)
    if not seller_ids:
        return Company.objects.none()
    return (
        Company.objects.filter(contacts__created_by__memberships__company_id__in=seller_ids).distinct().order_by("name")
    )


def find_client_company(user: CustomUser, *, inn: str = "", name: str = "") -> Optional[Company]:
    """Search-before-create WITHIN the seller's own book (by INN then name) — a seller
    never dedups against (or sees) another tenant's clients."""
    book = seller_clients(user)
    if inn:
        match = book.filter(stated_inn=inn).first()
        if match:
            return match
    if name:
        return book.filter(name__iexact=name.strip()).first()
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
    # Client books belong to seller teams; a non-seller would create an orphan company
    # invisible even to themselves (seller_clients scoping) — refuse instead.
    if not _seller_company_ids(seller):
        return None, "ONLY_SELLER_CAN_CREATE_CLIENTS"
    if not company_name or not contact_name:
        return None, "CLIENT_FIELDS_REQUIRED"
    if not (email or phone):
        return None, "CONTACT_NEEDS_EMAIL_OR_PHONE"

    # Soft de-dup WITHIN the seller's own book only (convenience; not a hard gate).
    # Cross-tenant duplicates are allowed (stated_inn is not unique).
    company = find_client_company(seller, inn=inn, name=company_name)
    company_created = False
    if company is None:
        company = Company.objects.create(
            name=company_name,
            stated_inn=inn,  # NOT the unique `inn` — cross-tenant dups allowed
            is_registered=False,  # rep-created, no platform login yet
        )
        client_type = CompanyType.objects.filter(code="CLIENT").first()
        if client_type:
            company.types.add(client_type)
        company_created = True

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
        )

    return {"company": company, "contact": contact, "company_created": company_created}, None
