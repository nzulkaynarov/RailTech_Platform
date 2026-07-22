"""«Документы 2.0» services — template CRUD + document generation lifecycle.

Rule 8: all business logic (sanitisation, placeholder resolution, snapshotting,
numbering, PDF dispatch, status transitions, entitlement/IDOR gates) lives here;
the ViewSets are thin wrappers. Placeholder substitution / sanitisation is delegated
to crm.services.document_placeholders (SSTI-safe flat replacement).
"""

from typing import Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.constants import FeatureKey
from accounts.models import CustomUser
from accounts.services.entitlements import has_entitlement

from ..constants import GeneratedDocumentStatusCode
from .document_placeholders import (
    PlaceholderContext,
    extract_placeholders,
    render_from_values,
    render_template,
    sanitize_template_html,
)

# Cap the stored template body so a settings.edit admin can't persist a multi-MB blob that is
# re-parsed/re-rendered on every generation (stored-DoS guard, A4/m6). 100 KB is far above any
# real letter/report.
MAX_TEMPLATE_BODY_CHARS = 100_000

# ── Owner-company + access resolution ───────────────────────────────────────


def resolve_owner_company_id(user: CustomUser) -> Optional[int]:
    """The company that OWNS a user's templates / generated documents.

    Prefers the primary membership; falls back to any active one. Documents are
    company-scoped (a seller's book, or a buyer's own letters)."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    primary = getattr(user, "primary_company", None)
    if primary is not None:
        return primary.id
    membership = user.memberships.filter(is_active=True).order_by("-is_primary", "id").first()
    return membership.company_id if membership else None


def _user_can_access_deal(user: CustomUser, deal) -> bool:
    """A deal is reachable if the user is a member of its owning (buyer) company OR a
    seller routed to it (hidden-competition scope)."""
    from accounts.services import is_member_of, seller_company_routed_to_deal

    if getattr(user, "is_superuser", False):
        return True
    return bool(is_member_of(user, deal.company_id) or seller_company_routed_to_deal(user, deal.id))


def _user_can_access_contact(user: CustomUser, contact, deal) -> bool:
    """A contact is reachable if it is in the seller's own client book, or it is the
    contact already attached to an accessible deal."""
    from accounts.services.clients import seller_clients

    if getattr(user, "is_superuser", False):
        return True
    if deal is not None and deal.contact_id == contact.id:
        return True
    return seller_clients(user).filter(pk=contact.company_id).exists()


def _status(code: str):
    """Resolve a GeneratedDocumentStatus row by code (raises loudly if unseeded — IRON RULE 1)."""
    from ..models import GeneratedDocumentStatus

    return GeneratedDocumentStatus.objects.get(code=code)


# ── Templates ───────────────────────────────────────────────────────────────


def _kind(code: str):
    from ..models import DocumentTemplateKind

    return DocumentTemplateKind.objects.get(code=code)


@transaction.atomic
def create_template(company, user: CustomUser, *, name: str, kind_code: str, body_html: str):
    """Create a company template: sanitise the body, derive its placeholders, save."""
    from ..models import DocumentTemplate

    if not (name or "").strip():
        raise ValidationError("TEMPLATE_NAME_REQUIRED")
    if len(body_html or "") > MAX_TEMPLATE_BODY_CHARS:
        raise ValidationError("TEMPLATE_BODY_TOO_LARGE")
    clean_html = sanitize_template_html(body_html)
    return DocumentTemplate.objects.create(
        company=company,
        name=name.strip(),
        kind=_kind(kind_code),
        body_html=clean_html,
        placeholders_used=extract_placeholders(clean_html),
        created_by=user,
    )


@transaction.atomic
def update_template(template, *, name=None, kind_code=None, body_html=None, is_active=None):
    """Update a template. Re-sanitises + re-derives placeholders when the body changes."""
    fields = ["updated_at"]
    if name is not None:
        if not name.strip():
            raise ValidationError("TEMPLATE_NAME_REQUIRED")
        template.name = name.strip()
        fields.append("name")
    if kind_code is not None:
        template.kind = _kind(kind_code)
        fields.append("kind")
    if body_html is not None:
        if len(body_html) > MAX_TEMPLATE_BODY_CHARS:
            raise ValidationError("TEMPLATE_BODY_TOO_LARGE")
        clean_html = sanitize_template_html(body_html)
        template.body_html = clean_html
        template.placeholders_used = extract_placeholders(clean_html)
        fields += ["body_html", "placeholders_used"]
    if is_active is not None:
        template.is_active = bool(is_active)
        fields.append("is_active")
    template.save(update_fields=fields)
    return template


# ── Generation lifecycle ─────────────────────────────────────────────────────


def _build_context(company, user, deal, contact) -> PlaceholderContext:
    quote = deal.active_quote if deal is not None else None
    contract = None
    if deal is not None:
        contract = (
            deal.contracts.select_related("status").order_by("-created_at").first()
        )
    return PlaceholderContext(company=company, deal=deal, contact=contact, quote=quote, contract=contract, user=user)


@transaction.atomic
def generate_document(company, user: CustomUser, *, template, deal=None, contact=None, title=None):
    """Render a template into a DRAFT GeneratedDocument (immutable snapshot).

    Gates: entitlement (document.generate) and IDOR (deal/contact belong to the
    acting company/user). Returns (document, None) or (None, ERROR_CODE)."""
    from accounts.services import is_platform_admin_viewer

    from ..models import GeneratedDocument

    if is_platform_admin_viewer(user):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    if not has_entitlement(company.id, FeatureKey.DOCUMENT_GENERATE):
        return None, "SUBSCRIPTION_REQUIRED"
    if deal is not None and not _user_can_access_deal(user, deal):
        return None, "DEAL_NOT_FOUND"
    if contact is not None and not _user_can_access_contact(user, contact, deal):
        return None, "CONTACT_NOT_FOUND"

    context = _build_context(company, user, deal, contact)
    # Snapshot the template body NOW: a DRAFT re-render (update_document_values) must run off this
    # frozen copy, never the live template.body_html — otherwise a later edit of the template would
    # silently rewrite an existing document (A4/M2).
    body_snapshot = template.body_html
    rendered_html, values, _warnings = render_template(body_snapshot, context)

    from .numbering import next_document_number

    document = GeneratedDocument.objects.create(
        company=company,
        deal=deal,
        contact=contact,
        template=template,
        number=next_document_number("DOC", "DOC", company=company),
        status=_status(GeneratedDocumentStatusCode.DRAFT),
        title=(title or template.name)[:255],
        values=values,
        rendered_html=rendered_html,
        body_html_snapshot=body_snapshot,
        created_by=user,
    )
    return document, None


@transaction.atomic
def update_document_values(document, values: dict) -> Tuple[Optional[object], Optional[str]]:
    """Edit a DRAFT document's placeholder values, re-render its HTML off the stored
    body, and invalidate any stale PDF (invalidate-on-write, mirrors КП #379). Only
    DRAFT is editable — an issued/cancelled document is a frozen archive."""
    if document.status_code != GeneratedDocumentStatusCode.DRAFT:
        return None, "DOCUMENT_NOT_EDITABLE"
    # Re-render off the frozen body snapshot (A4/M2), falling back to the live template only for
    # rows created before the snapshot column existed.
    body = document.body_html_snapshot or document.template.body_html
    # Only known placeholder codes may carry a value — reject arbitrary keys (A4/m6).
    incoming = {code: val for code, val in (values or {}).items() if code in (document.values or {})}
    merged = dict(document.values or {})
    merged.update(incoming)
    document.values = merged
    document.rendered_html = render_from_values(body, merged)
    fields = ["values", "rendered_html", "updated_at"]
    if document.pdf_file:
        document.pdf_file.delete(save=False)
        document.pdf_file = None
        fields.append("pdf_file")
    document.save(update_fields=fields)
    return document, None


@transaction.atomic
def issue_document(document, user: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """DRAFT → ISSUED: freeze the document and dispatch the off-thread PDF render (ARCH-03)."""
    from accounts.services import is_platform_admin_viewer

    if is_platform_admin_viewer(user):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Re-check entitlement at issue time (A4/m4): a subscription may have lapsed after the DRAFT was
    # created, and issuing is what produces the deliverable PDF.
    if not has_entitlement(document.company_id, FeatureKey.DOCUMENT_GENERATE):
        return None, "SUBSCRIPTION_REQUIRED"
    if document.status_code != GeneratedDocumentStatusCode.DRAFT:
        return None, "DOCUMENT_ALREADY_ISSUED"
    document.status = _status(GeneratedDocumentStatusCode.ISSUED)
    document.issued_at = timezone.now()
    document.save(update_fields=["status", "issued_at", "updated_at"])

    from ..tasks import render_document_pdf

    document_id = document.id
    transaction.on_commit(lambda: render_document_pdf.delay("generated", document_id))
    return document, None


@transaction.atomic
def cancel_document(document, user: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """DRAFT or ISSUED → CANCELLED. An already-cancelled document raises."""
    from accounts.services import is_platform_admin_viewer

    if is_platform_admin_viewer(user):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    if document.status_code == GeneratedDocumentStatusCode.CANCELLED:
        return None, "DOCUMENT_ALREADY_CANCELLED"
    document.status = _status(GeneratedDocumentStatusCode.CANCELLED)
    fields = ["status", "updated_at"]
    # Drop the rendered PDF so a cancelled document can't still be downloaded via the API (A4/m7).
    if document.pdf_file:
        document.pdf_file.delete(save=False)
        document.pdf_file = None
        fields.append("pdf_file")
    document.save(update_fields=fields)
    return document, None


def _render_generated_pdf(document) -> None:
    """Render a GeneratedDocument's snapshot HTML to its pdf_file (WeasyPrint, off-thread)."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from .documents import document_brand_context

    html_string = render_to_string(
        "crm/generated_document_pdf.html",
        {
            "document": document,
            "company": document.company,
            **document_brand_context(document.company),
        },
    )
    buffer = BytesIO()
    HTML(string=html_string).write_pdf(buffer)
    document.pdf_file.save(f"Document_{document.number}.pdf", ContentFile(buffer.getvalue()), save=True)
