"""Seller-managed (offline) clients — the CRM client base.

World-standard Account(Company)+Contact: a seller records a client they reached through
other channels (no self-registration), then builds a КП for it. Search-before-create
de-dup avoids duplicate accounts (the #1 CRM pitfall). See
Docs/ops/client-base-design-2026-06-24.md.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction

from ..models import Company, CompanyType, Contact, CustomUser

logger = logging.getLogger(__name__)


def find_client_company(*, inn: str = "", name: str = "") -> Optional[Company]:
    """Search-before-create: match an existing account by INN (exact) then name (iexact)."""
    if inn:
        match = Company.objects.filter(inn=inn).first()
        if match:
            return match
    if name:
        return Company.objects.filter(name__iexact=name.strip()).first()
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
    if not company_name or not contact_name:
        return None, "CLIENT_FIELDS_REQUIRED"
    if not (email or phone):
        return None, "CONTACT_NEEDS_EMAIL_OR_PHONE"

    company = find_client_company(inn=inn, name=company_name)
    company_created = False
    if company is None:
        company = Company.objects.create(
            name=company_name,
            inn=inn or None,
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
