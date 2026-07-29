"""Seller-managed (offline) clients — the CRM client base.

World-standard Account(Company)+Contact: a seller records a client they reached through
other channels (no self-registration), then builds a КП for it. Search-before-create
de-dup avoids duplicate accounts (the #1 CRM pitfall). See
Docs/dev/specs/client-base-design-2026-06-24.md.
"""

import logging
from typing import Optional, Tuple

from django.conf import settings
from django.db import transaction

from ..models import Company, CompanyType, Contact, CustomUser

logger = logging.getLogger(__name__)


def _seller_company_ids(user: CustomUser) -> list:
    """The SUPPLIER/MANUFACTURER companies the user is an active member of."""
    return list(user.memberships.filter(is_active=True).in_seller_company().values_list("company_id", flat=True))


def seller_clients(user: CustomUser):
    """The seller's OWN client base (team-level): companies its members created as
    offline clients (via a Contact) — NOT a platform-wide listing (confidentiality).
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
    # Cross-tenant duplicates are allowed and reconciled by the admin at KYC.
    company = find_client_company(seller, inn=inn, name=company_name)
    company_created = False
    if company is None:
        company = Company.objects.create(
            name=company_name,
            stated_inn=inn,  # NOT the unique `inn` — cross-tenant dups allowed pre-KYC
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

    # Counterparty book (Phase B): recording an offline client IS the relationship —
    # the seller's book gains a CLIENT edge owned by the creator's seller company.
    from .permissions import primary_seller_company_id

    owner_company_id = primary_seller_company_id(seller)
    if owner_company_id:
        from crm.models import RelationshipDirection, RelationshipSource
        from crm.services.relationships import touch_relationship

        touch_relationship(
            owner_company_id=owner_company_id,
            counterparty_company_id=company.id,
            direction=RelationshipDirection.CLIENT,
            source=RelationshipSource.OFFLINE_CREATED,
            owner_member=seller.memberships.filter(company_id=owner_company_id, is_active=True).first(),
        )

    return {"company": company, "contact": contact, "company_created": company_created}, None


CLIENT_INVITE_TTL_DAYS = 14


def _hash_invite_token(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def send_client_invite(*, seller: CustomUser, contact_id: int) -> Tuple[Optional[object], Optional[str]]:
    """Invite an offline client's contact to register and CLAIM its existing Company (Phase D).

    Turns the seller's offline book into registered users without a duplicate. Returns
    (ClientInvite, None) or (None, error_code). Scoped: the contact must be in the seller's OWN
    book, its company still offline, and the contact reachable by email.
    """
    import secrets
    from datetime import timedelta

    from django.utils import timezone

    from notifications.emails import EmailDeliveryError, email_brand, send_templated_email

    from ..models import ClientInvite, Contact

    contact = Contact.objects.filter(pk=contact_id).select_related("company").first()
    if contact is None:
        return None, "CONTACT_NOT_FOUND"
    if not seller_clients(seller).filter(pk=contact.company_id).exists():
        return None, "CONTACT_NOT_IN_YOUR_BOOK"
    if contact.company.is_registered:
        return None, "COMPANY_ALREADY_REGISTERED"
    if not contact.email:
        return None, "CONTACT_HAS_NO_EMAIL"
    if CustomUser.objects.filter(email__iexact=contact.email).exists():
        return None, "USER_EMAIL_ALREADY_EXISTS"

    token = secrets.token_urlsafe(32)
    invite = ClientInvite.objects.create(
        company=contact.company,
        contact=contact,
        created_by=seller,
        email=contact.email,
        token_hash=_hash_invite_token(token),
        expires_at=timezone.now() + timedelta(days=CLIENT_INVITE_TTL_DAYS),
    )
    invite_url = f"{settings.FRONTEND_URL}/register?invite={token}"
    try:
        send_templated_email(
            "invite_client",
            {
                "company_name": contact.company.name,
                "contact_name": contact.name,
                "invite_url": invite_url,
                # D1e white-label: the inviting seller's brand opens the email.
                **email_brand(contact.company),
            },
            to=[contact.email],
            channel="transactional",
            user=seller,
        )
    except EmailDeliveryError:
        invite.delete()
        return None, "EMAIL_SEND_FAILED"
    return invite, None


def accept_client_invite(user: CustomUser, token: str):
    """Resolve a raw invite token to its live ClientInvite (unused, unexpired, company still
    offline). Returns (invite, None) or (None, error_code). Does NOT mutate — the caller
    (submit_company_profile) performs the claim inside its own transaction."""
    from django.utils import timezone

    from ..models import ClientInvite

    invite = ClientInvite.objects.filter(token_hash=_hash_invite_token(token or "")).select_related("company").first()
    if invite is None or invite.accepted_at is not None or invite.expires_at <= timezone.now():
        return None, "CLIENT_INVITE_INVALID"
    if invite.company.is_registered:
        return None, "COMPANY_ALREADY_REGISTERED"
    return invite, None
