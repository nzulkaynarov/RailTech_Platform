"""«Документы 2.0» services — template CRUD + document generation lifecycle.

Rule 8: all business logic (sanitisation, placeholder resolution, snapshotting,
numbering, PDF dispatch, status transitions, permission/IDOR gates) lives here;
the ViewSets are thin wrappers. Placeholder substitution / sanitisation is delegated
to crm.services.document_placeholders (SSTI-safe flat replacement).
"""

from types import SimpleNamespace
from typing import Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import CustomUser
from crm.services.pdf_storage import save_rendered_pdf

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

# TTL of the public no-login link minted when a document is ISSUED (mirrors the КП public link
# lifecycle). A generated letter/report is a point-in-time deliverable; 30 days matches the КП
# window and keeps a stale emailed link from living forever.
DOCUMENT_PUBLIC_TOKEN_TTL_DAYS = 30

# Brand-letterhead snapshot (J-a). document_brand_context() returns LIVE model instances (seller
# Company, seller_profile CompanyDocumentProfile) that are NOT JSON-serializable, so on issue we
# flatten exactly the attributes _document_base.html reads into brand_snapshot. An ISSUED document
# then renders off that frozen copy — its шапка/реквизиты never «плывут» when the company later
# edits its CompanyDocumentProfile (Odoo/PandaDoc immutability principle).
_BRAND_SELLER_FIELDS = ("name", "inn", "phone", "email", "legal_address")
_BRAND_PROFILE_FIELDS = (
    "legal_name",
    "accent_color",
    "inn",
    "legal_address",
    "bank_details",
    "signatory_name",
    "signatory_position",
    "footer_text",
    # _document_base.html gates the letterhead bank block on this toggle — freeze it too, else an
    # ISSUED document's header silently drops (or gains) the bank requisites after the company edits.
    "show_bank_in_header",
)
_BRAND_SCALAR_FIELDS = (
    "seller_logo_url",
    "show_logo",
    "show_lead_time",
    "show_fx_note",
    "accent",
    "accent_contrast",
    # D2 document theme: _document_base.html reads these (body layout class + :root font/tint vars).
    # Without them a frozen snapshot rebuilds to the DEFAULT theme, so an ISSUED document's PDF loses
    # the seller's layout preset / font / secondary tint that its DRAFT preview showed (fidelity gap).
    "layout_preset",
    "font_stack",
    "secondary",
)


def _serialize_brand_context(brand: dict) -> dict:
    """Flatten a live ``document_brand_context()`` into a JSON-serializable snapshot dict.

    The two model instances (seller Company, seller_profile CompanyDocumentProfile) are reduced to
    the scalar attributes the PDF base template reads; every other key is already a scalar."""
    seller = brand.get("seller")
    profile = brand.get("seller_profile")
    snapshot = {key: brand.get(key) for key in _BRAND_SCALAR_FIELDS}
    snapshot["seller"] = {field: getattr(seller, field, None) for field in _BRAND_SELLER_FIELDS} if seller else None
    snapshot["seller_profile"] = (
        {field: getattr(profile, field, None) for field in _BRAND_PROFILE_FIELDS} if profile else None
    )
    return snapshot


def _brand_context_from_snapshot(snapshot: dict) -> dict:
    """Rebuild the PDF render context from a stored brand snapshot: SimpleNamespace stubs stand in
    for the seller/profile model instances so ``_document_base.html`` renders unchanged off the
    frozen data."""
    context = {key: snapshot.get(key) for key in _BRAND_SCALAR_FIELDS}
    seller = snapshot.get("seller")
    profile = snapshot.get("seller_profile")
    context["seller"] = SimpleNamespace(**seller) if seller else None
    context["seller_profile"] = SimpleNamespace(**profile) if profile else None
    return context


# ── Letterhead preview (T1-a) ────────────────────────────────────────────────
# The KEY insight behind «Документы 2.0» T1: the branded шапка/колонтитул already print the owner
# company's name/ИНН/адрес/лого/подпись (crm/_document_base.html). A preview that shows only the
# sanitised BODY hides that letterhead, so the author re-types the same requisites into the body and
# the real PDF prints them TWICE. So both previews (editor + registry sheet) render the FULL branded
# document — header + body + footer — off this flat, JSON-serializable letterhead slice.


def _flatten_brand_for_preview(brand: dict) -> dict:
    """Flatten a ``document_brand_context()`` bundle (or a snapshot-rebuilt one) into the flat, JSON
    letterhead the SPA header/footer render. Reads the SAME fields the PDF base template prints:
    seller_profile.legal_name → seller.name → platform fallback; ИНН/адрес/телефон/почта; logo (only
    when show_logo); footer_text; accent + on-accent contrast; optional signatory. Accepts both live
    model instances and SimpleNamespace stubs (getattr with a default works for either)."""
    seller = brand.get("seller")
    profile = brand.get("seller_profile")
    platform_name = brand.get("platform_name") or "ERP"
    seller_name = getattr(profile, "legal_name", None) or getattr(seller, "name", None) or platform_name
    inn = getattr(profile, "inn", None) or getattr(seller, "inn", None) or ""
    address = getattr(profile, "legal_address", None) or getattr(seller, "legal_address", None) or ""
    footer = getattr(profile, "footer_text", None) or f"Документ сформирован в {platform_name}"
    logo = brand.get("seller_logo_url") if brand.get("show_logo", True) else None
    return {
        "seller_name": seller_name,
        "inn": inn or "",
        "address": address or "",
        "phone": getattr(seller, "phone", "") or "",
        "email": getattr(seller, "email", "") or "",
        "logo_url": logo,
        "footer_text": footer,
        "accent": brand.get("accent") or "#15294d",
        "accent_contrast": brand.get("accent_contrast") or "#ffffff",
        "signatory_name": getattr(profile, "signatory_name", None) or "",
        "signatory_position": getattr(profile, "signatory_position", None) or "",
    }


def brand_letterhead_preview(company) -> dict:
    """Flat letterhead slice for a company's LIVE branding — the editor preview (no document yet)."""
    from .documents import document_brand_context

    return _flatten_brand_for_preview(document_brand_context(company))


def brand_letterhead_for_document(document) -> dict:
    """Flat letterhead slice for a generated document: the FROZEN brand snapshot once issued (J-a
    immutability), else the owner company's live branding for a DRAFT."""
    return _flatten_brand_for_preview(document_render_brand(document))


def document_render_brand(document) -> dict:
    """The brand render context a document's PDF renders from: the FROZEN snapshot once issued (J-a),
    else the owner company's live branding for a DRAFT. Single source shared by the PDF renderer, the
    public HTML page, and the 1:1 registry preview — so all three read the same letterhead."""
    from .documents import document_brand_context

    if document.brand_snapshot:
        return _brand_context_from_snapshot(document.brand_snapshot)
    return document_brand_context(document.company)


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
    """A deal is reachable if the user is a member of its owning (buyer) company OR own-company
    staff (the single seller)."""
    from accounts.services import is_member_of, sees_all_deals

    if sees_all_deals(user):
        return True
    return bool(is_member_of(user, deal.company_id))


def _user_owns_document(user: CustomUser, document) -> bool:
    """True if the acting user belongs to the company that OWNS the document.

    The registry queryset is widened (II-2) so a counterparty sees ISSUED documents on shared
    deals read-only — this gate keeps every MUTATION (issue/cancel) owner-only, closing the hole
    where a buyer who can now see a seller's ISSUED document could cancel it."""
    from accounts.services import is_member_of

    if getattr(user, "is_superuser", False):
        return True
    return is_member_of(user, document.company_id)


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


def _assert_legal_template_integrity(kind_code: str, body_html: str, is_active: bool) -> None:
    """E2 (spec-editable-outgoing-documents): АКТИВНЫЙ шаблон юридического вида обязан
    содержать структурные блоки — без таблицы позиций, итогов и подписей/реквизитов документ
    перестаёт быть документом. Черновик (is_active=False) правится свободно; проверка
    срабатывает на активации. Наш аналог «lock block position» у PandaDoc."""
    if not is_active:
        return
    from .document_blocks import missing_required_blocks

    if missing_required_blocks(kind_code, body_html):
        raise ValidationError("TEMPLATE_MISSING_REQUIRED_BLOCKS")


@transaction.atomic
def create_template(company, user: CustomUser, *, name: str, kind_code: str, body_html: str):
    """Create a company template: sanitise the body, derive its placeholders, save."""
    from ..models import DocumentTemplate

    if not (name or "").strip():
        raise ValidationError("TEMPLATE_NAME_REQUIRED")
    if len(body_html or "") > MAX_TEMPLATE_BODY_CHARS:
        raise ValidationError("TEMPLATE_BODY_TOO_LARGE")
    clean_html = sanitize_template_html(body_html)
    # Новый шаблон рождается активным (модельный default) — целостность проверяется сразу.
    _assert_legal_template_integrity(kind_code, clean_html, True)
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
    # E2: проверяем ИТОГОВОЕ состояние — какая пара (вид, тело) станет активной после правки.
    _assert_legal_template_integrity(template.kind.code, template.body_html, template.is_active)
    template.save(update_fields=fields)
    return template


# ── Live preview (editor) ────────────────────────────────────────────────────


def _demo_context(company, user) -> PlaceholderContext:
    """Sample PlaceholderContext for the editor preview: the caller's REAL company
    (so ``company.*`` shows their own data) plus plausible fictional deal / counterparty /
    quote / contract stand-ins. Lightweight SimpleNamespace stubs — nothing is persisted."""
    counterparty = SimpleNamespace(name="ООО Пример", inn="301234567")
    deal = SimpleNamespace(id=1024, title="Демо-сделка", company_id=1, company=counterparty)
    contact = SimpleNamespace(name="ООО Пример", company_id=1, company=counterparty)
    quote = SimpleNamespace(number="КП-2026-00042", total_incl_vat="12 500 000 UZS")
    contract = SimpleNamespace(number="ДГ-2026-00007")
    return PlaceholderContext(company=company, deal=deal, contact=contact, quote=quote, contract=contract, user=user)


def render_document_html_from_body(company, rendered_body_html: str, *, brand: dict = None) -> str:
    """Wrap an already-rendered document BODY in the FULL branded document HTML using the SAME
    template the PDF renders (crm/generated_document_pdf.html → _document_base.html).

    This is the 1:1 preview primitive: the editor/registry preview the SPA shows in an iframe is
    literally the document template — header (лого/реквизиты/банк/тема) + body + footer — so it
    cannot drift from the WeasyPrint PDF the way a hand-written React letterhead did. `brand`
    defaults to the company's LIVE branding; pass a snapshot-rebuilt context to preview an ISSUED
    document exactly as its frozen PDF renders. Returns HTML only (no WeasyPrint — instant, cheap
    on every keystroke, never blocks the request thread; ARCH-03)."""
    from django.template.loader import render_to_string

    from .documents import document_brand_context

    if brand is None:
        brand = document_brand_context(company)
    document_stub = SimpleNamespace(
        rendered_html=rendered_body_html,
        number="DOC-2026-00001",
        title="Образец документа",
        created_at=timezone.now(),
    )
    return render_to_string(
        "crm/generated_document_pdf.html",
        {"document": document_stub, "company": None, **brand},
    )


def preview_template(company, user: CustomUser, *, body_html: str) -> dict:
    """Render a template body against SAMPLE data for the live editor preview.

    Sanitises the body, resolves placeholders on a demo context (real company + fictional
    deal/counterparty/quote/contract), and returns the rendered HTML plus the resolved and
    unknown placeholder codes. Never touches the DB — no document/template is created."""
    if len(body_html or "") > MAX_TEMPLATE_BODY_CHARS:
        raise ValidationError("TEMPLATE_BODY_TOO_LARGE")
    clean_html = sanitize_template_html(body_html)
    rendered_html, values, warnings = render_template(clean_html, _demo_context(company, user))
    # Структурные блоки юридических видов (E1b) собираются только при печати настоящего
    # документа — в превью на месте токена встаёт подписанная заглушка, а не предупреждение.
    from .document_blocks import preview_block_stubs, render_document_body

    stubs = preview_block_stubs()
    rendered_html = render_document_body(rendered_html, blocks=stubs, scalars={})
    warnings = [code for code in warnings if code not in stubs]
    return {
        "rendered_html": rendered_html,
        "placeholders_used": list(values.keys()),
        "warnings": warnings,
        # The FULL branded document = header (name/ИНН/лого) + body + footer, so the author sees the
        # requisites are already in the letterhead and stops duplicating them in the body (T1-a).
        "brand": brand_letterhead_preview(company),
        # 1:1 preview: the whole document rendered by the REAL PDF template. The SPA drops this into
        # an iframe instead of re-implementing the letterhead in React (which drifted from the PDF).
        "document_html": render_document_html_from_body(company, rendered_html),
    }


# ── Generation lifecycle ─────────────────────────────────────────────────────


def _build_context(company, user, deal, contact) -> PlaceholderContext:
    quote = deal.active_quote if deal is not None else None
    contract = None
    if deal is not None:
        contract = deal.contracts.select_related("status").order_by("-created_at").first()
    return PlaceholderContext(company=company, deal=deal, contact=contact, quote=quote, contract=contract, user=user)


@transaction.atomic
def generate_document(company, user: CustomUser, *, template, deal=None, contact=None, title=None):
    """Render a template into a DRAFT GeneratedDocument (immutable snapshot).

    Gates: quote.build permission and IDOR (deal/contact belong to the
    acting company/user). Returns (document, None) or (None, ERROR_CODE)."""
    from accounts.services.permissions import member_has_permission

    from ..models import GeneratedDocument

    # Producing a branded company document is a build action — gate it on the quote.build CompanyRole
    # permission (§2), mirroring the КП builder. A buy-only member (no quote.build) must not issue
    # letters on the company's letterhead. OWNER/company-admin keeps it via the legacy OWNER fallback.
    if not member_has_permission(user, company.id, "deal.manage"):
        return None, "ROLE_NOT_PERMITTED"
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
    """DRAFT → ISSUED: freeze the document, mint the public no-login token, dispatch the
    off-thread PDF render (ARCH-03) and notify the deal counterparty (II-1/II-2)."""
    import secrets

    from accounts.services.permissions import member_has_permission

    if not _user_owns_document(user, document):
        return None, "DOCUMENT_NOT_FOUND"
    # Issuing freezes the document + produces the deliverable PDF — a build action, gated on
    # quote.build like generation (§2). Checked for the OWNING company (owner-gate already passed).
    if not member_has_permission(user, document.company_id, "deal.manage"):
        return None, "ROLE_NOT_PERMITTED"
    if document.status_code != GeneratedDocumentStatusCode.DRAFT:
        return None, "DOCUMENT_ALREADY_ISSUED"
    from integration.services import document_events

    from .documents import document_brand_context

    # document.created на шину rt_bus — на переходе «не выпущен → выпущен», в транзакции выпуска.
    with document_events.watch_document_issue("generated", document):
        document.status = _status(GeneratedDocumentStatusCode.ISSUED)
        document.issued_at = timezone.now()
        # Freeze the letterhead (лого/реквизиты/accent) at issue so the ISSUED PDF never «плывёт» when
        # the company later edits its CompanyDocumentProfile (J-a, immutability).
        document.brand_snapshot = _serialize_brand_context(document_brand_context(document.company))
        fields = ["status", "issued_at", "brand_snapshot", "updated_at"]
        # Mint the public link ONCE, on issue (never on DRAFT) — the same pattern as Quote.public_access_token.
        if not document.public_access_token:
            document.public_access_token = secrets.token_urlsafe(32)
            document.public_token_expires_at = timezone.now() + timezone.timedelta(days=DOCUMENT_PUBLIC_TOKEN_TTL_DAYS)
            fields += ["public_access_token", "public_token_expires_at"]
        document.save(update_fields=fields)

    from ..tasks import render_document_pdf

    document_id = document.id
    transaction.on_commit(lambda: render_document_pdf.delay("generated", document_id))
    _notify_document_issued_to_counterparty(document)
    return document, None


def _notify_document_issued_to_counterparty(document) -> None:
    """Alert the deal's OTHER-side team that a document was issued to them (read-only «получено»).

    FK→deal so the deep-link derives from it (platform convention, mirrors the invoice notify).
    Only fires when the document is bound to a deal with a real counterparty company that is NOT the
    issuing company — a solo deal (deal.company_id is None) has no one to notify."""
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    deal = document.deal
    if deal is None or not deal.company_id or deal.company_id == document.company_id:
        return
    info_type = NotificationType.objects.filter(code="INFO").first()
    member_user_ids = deal.company.members.filter(is_active=True).values_list("user_id", flat=True)
    notifications = [
        Notification(
            user_id=uid,
            type=info_type,
            title="Получен документ",
            message=f"По сделке #{deal.pk} вам направлен документ {document.number}",
            link="/crm/documents",
            deal=deal,
            event_code="document.received",
            event_params={"deal_id": deal.pk, "number": document.number},
        )
        for uid in member_user_ids
    ]
    for notif in Notification.objects.bulk_create(notifications):
        push_notification_ws(notif)


@transaction.atomic
def cancel_document(document, user: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """DRAFT or ISSUED → CANCELLED. An already-cancelled document raises."""

    if not _user_owns_document(user, document):
        return None, "DOCUMENT_NOT_FOUND"
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


# ── Public link + delivery (II-1 / II-2) ─────────────────────────────────────


def public_document_gate(document) -> Optional[str]:
    """Reachability of a document's PUBLIC (no-login) token link. Returns an error CODE
    (mapped to 404/410 by the view) or None when live. ONLY an ISSUED document is ever
    served publicly — a DRAFT (no token) or CANCELLED document is never reachable."""
    from django.utils import timezone

    if document is None or document.status_code != GeneratedDocumentStatusCode.ISSUED:
        return "NOT_FOUND"
    if document.public_token_revoked:
        return "DOCUMENT_LINK_REVOKED"
    if document.public_token_expires_at and document.public_token_expires_at < timezone.now():
        return "DOCUMENT_LINK_EXPIRED"
    return None


def public_document_url(document) -> Optional[str]:
    """Public no-login link built from the minted token, or None before issue / after revoke.
    ONE place owns the URL pattern (Rule 8) — shared by the send-email task and the serializer.
    A revoked link returns None so the SPA hides the dead «Копировать ссылку» affordance (J-b)."""
    from django.conf import settings

    token = getattr(document, "public_access_token", None)
    if not token or getattr(document, "public_token_revoked", False):
        return None
    return f"{settings.FRONTEND_URL}/api/v1/public/documents/{token}/"


@transaction.atomic
def revoke_document_public_link(document, user: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """Pull an ISSUED document's public no-login link (owner-only). Idempotent — a further public
    open then returns 410 (public_document_gate → DOCUMENT_LINK_REVOKED). Mirrors the КП
    revoke-public-link (Quote.revoke_public_link). Returns (document, None) or (None, ERROR_CODE)."""

    if not _user_owns_document(user, document):
        return None, "DOCUMENT_NOT_FOUND"
    # Only an ISSUED document that still carries a minted token has a live link to pull.
    if document.status_code != GeneratedDocumentStatusCode.ISSUED or not document.public_access_token:
        return None, "DOCUMENT_LINK_NOT_ACTIVE"
    if not document.public_token_revoked:
        document.public_token_revoked = True
        document.save(update_fields=["public_token_revoked", "updated_at"])
    return document, None


def party_visible_document_q(user):
    """Q matching ISSUED documents a user may see as the COUNTERPARTY — the «полученные письма»
    read-only surface (II-2). Combined by the ViewSet with the own-company clause; DRAFT/CANCELLED
    of another company are never included.

    As the buyer (the user is a member of the deal's company) — any ISSUED document on their own
    deal is addressed to them. As own-company staff (the seller of every deal) — the client's own
    ISSUED letters on any deal (`company == deal.company`)."""
    from django.db.models import F, Q

    from accounts.services import is_seller

    company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    as_buyer = Q(deal__company_id__in=company_ids)
    visible = as_buyer
    if is_seller(user):
        visible |= Q(deal__isnull=False) & Q(company_id=F("deal__company_id"))
    return Q(status__code=GeneratedDocumentStatusCode.ISSUED) & visible


def resolve_document_recipient(document, override_email=None):
    """The document's outgoing email recipient as ``(email, display_name)``, or ``None``.

    An explicit override (seller typed an address) wins; else the document's own contact, then the
    deal's offline contact, then the deal's registered buyer, then the buyer company's email."""
    if override_email:
        return override_email, override_email
    contact = getattr(document, "contact", None)
    if contact and contact.email:
        return contact.email, contact.name
    deal = document.deal
    if deal is not None:
        deal_contact = getattr(deal, "contact", None)
        if deal_contact and deal_contact.email:
            return deal_contact.email, deal_contact.name
        client = getattr(deal, "client", None)
        if client and client.email:
            return client.email, (client.get_full_name() or client.email)
        if deal.company_id and deal.company and deal.company.email:
            return deal.company.email, deal.company.name
    return None


def send_document_email(document, user: CustomUser, *, to=None) -> Tuple[Optional[object], Optional[str]]:
    """Email an ISSUED document (public link in the body) to its recipient. Thin: gate → resolve
    recipient → enqueue the off-thread task (ARCH-03). Returns (recipient_email, None) or (None, CODE)."""
    from accounts.services.permissions import member_has_permission

    if not _user_owns_document(user, document):
        return None, "DOCUMENT_NOT_FOUND"
    # Dispatching the branded document is part of the build/send flow — gate on quote.build (§2),
    # so a buy-only member can't aim the company's letterhead email.
    if not member_has_permission(user, document.company_id, "deal.manage"):
        return None, "ROLE_NOT_PERMITTED"
    if document.status_code != GeneratedDocumentStatusCode.ISSUED:
        return None, "DOCUMENT_NOT_ISSUED"
    recipient = resolve_document_recipient(document, override_email=to)
    if recipient is None:
        return None, "DOCUMENT_NO_RECIPIENT"
    to_email, _to_name = recipient

    from ..tasks import send_document_email as send_document_email_task

    document_id = document.id
    transaction.on_commit(lambda: send_document_email_task.delay(document_id, to_email))
    return to_email, None


def _render_generated_pdf(document) -> None:
    """Render a GeneratedDocument's snapshot HTML to its pdf_file (WeasyPrint, off-thread)."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from .documents import brand_context_for_pdf

    # document_render_brand: frozen letterhead snapshot (J-a) for ISSUED, live brand for DRAFT.
    # brand_context_for_pdf: inline the logo as a data: URI (WeasyPrint can't resolve the relative
    # /media/… URL prod storage yields — broken-image box otherwise).
    html_string = render_to_string(
        "crm/generated_document_pdf.html",
        {
            "document": document,
            "company": document.company,
            **brand_context_for_pdf(document_render_brand(document)),
        },
    )
    buffer = BytesIO()
    HTML(string=html_string).write_pdf(buffer)
    save_rendered_pdf(document, f"Document_{document.number}.pdf", ContentFile(buffer.getvalue()))
