"""КП lifecycle state machine — render/send/approve/reject/submit/force-approve.

Split out of the monolithic ``crm/services/quotes.py`` (ARCH refactor) — behaviour
unchanged. ``QuoteLifecycleService`` is a single cohesive transactional state-machine
class; its methods share the same guard vocabulary and FSM invariants, so the class is
kept whole here rather than fractured into render/approval mixins. Under the project's
500-line file limit (DT3), the leaf, side-effect-free helpers are split into siblings:

  * ``lifecycle_gates`` — the pure render / send / submit precondition checks
    (loss-prevention / below-floor policy in ONE place).
  * ``lifecycle_audit`` — the timeline events + client notification emitted on send.

The class methods orchestrate: fetch → gate → mutate → side-effect. ``compute_quote_economics``
is imported HERE (not re-derived in the gates) so the below-floor send tests can patch
``crm.services.quotes.lifecycle.compute_quote_economics``.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction

from accounts.models import CustomUser
from core.audit import log_admin_action
from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import Quote, QuoteStatus
from crm.services.deals import transition_deal_stage
from crm.services.pdf_storage import save_rendered_pdf

from . import lifecycle_audit
from ._shared import _log_quote, _set_quote_status
from .lifecycle_gates import (
    assert_renderable,
    assert_send_economics,
    assert_sendable,
    assert_submittable,
    resolve_submit_company,
)
from .pricing import compute_quote_economics

logger = logging.getLogger(__name__)


class QuoteLifecycleService:
    """Manages Quote state transitions: generate PDF, send, approve, reject."""

    @staticmethod
    def assert_pdf_renderable(quote_id: int) -> None:
        """Run the КП render guards WITHOUT rendering (ARCH-03).

        Views call this to surface the 409 guard errors synchronously while the
        WeasyPrint render itself happens off-thread in crm.tasks.render_document_pdf.
        """
        quote = Quote.objects.select_related("deal__company", "prepared_by").prefetch_related("items").get(pk=quote_id)
        assert_renderable(quote)

    @staticmethod
    @transaction.atomic
    def generate_pdf(quote_id: int) -> Quote:
        """Generate PDF for a quote using WeasyPrint."""
        from io import BytesIO

        from django.core.files.base import ContentFile
        from django.template.loader import render_to_string
        from weasyprint import HTML

        quote = (
            Quote.objects.select_related(
                "deal__company", "status", "tax_country", "prepared_by", "quote_currency", "delivery_basis"
            )
            .prefetch_related("items__product__domain_type")
            .get(pk=quote_id)
        )

        seller_company = assert_renderable(quote)
        # Shared branding bundle (issuing company + its document profile + logo) — the same
        # shape every document feeds the base template.
        from crm.services.documents import (
            brand_context_for_pdf,
            client_optional_items,
            client_projection_items,
            document_brand_context,
            public_quote_qr,
            public_quote_url,
            quote_document_extras,
        )

        projected_items = client_projection_items(quote)

        # «Фирменный бланк» extras (spec-kp-blank + D1): cover letter, structured «Условия поставки»
        # and the 3-line VAT totals — ONE shared builder (quote_document_extras) also used by the
        # public online page, so the PDF and its QR «оригинал» can never diverge. Read-only.
        extras = quote_document_extras(quote, seller_company)
        html_string = render_to_string(
            "crm/quote_pdf.html",
            {
                "quote": quote,
                "totals": extras["totals"],
                "cover_text": extras["cover_text"],
                "quote_terms": extras["quote_terms"],
                # Governance: a КП is an OFFER only once frozen on send. Until then (draft or
                # internally-approved-but-unsent) the PDF carries a «ЧЕРНОВИК» stamp, so a copy
                # leaked out-of-band cannot pass as a binding offer (matches send_to_client policy).
                "is_draft": quote.frozen_at is None,
                # Only surface the per-line «Срок» column when at least one line actually carries a
                # lead time — otherwise it prints a column of «—» that duplicates the single КП-level
                # «Срок поставки» in the terms block (client confusion).
                "has_line_lead_time": any(item.get("lead_time_days") for item in projected_items),
                # Client projection: charges distributed into per-line delivered prices (no
                # goods-vs-charges breakout — confidentiality). Lines sum to quote.total_excl_vat.
                # Includes SECTION/NOTE rows (display_type) in position order; optional lines are
                # rendered separately below the totals via `optional_items` (off-total offer).
                "items": projected_items,
                "optional_items": client_optional_items(quote),
                "company": quote.deal.company,
                # Offline client for the «Покупатель» card when deal.company is NULL (solo deal) —
                # the base parties block shows the contact instead of an empty grey box (D1).
                "contact": quote.deal.contact,
                # Public «Принять онлайн» link + QR — present only after send (token minted), so the
                # seller-facing draft PDF has no CTA while the sent/public КП does (F-09).
                "public_quote_url": public_quote_url(quote),
                "public_quote_qr": public_quote_qr(quote),
                # brand_context_for_pdf: inline the logo as a data: URI — WeasyPrint can't resolve
                # the relative /media/… URL prod storage yields (broken-image box on every PDF).
                **brand_context_for_pdf(document_brand_context(seller_company)),
            },
        )

        pdf_file = BytesIO()
        HTML(string=html_string).write_pdf(pdf_file)

        # Владелец 27-07: «имя файла разрознено с настройками компании» — файл называется
        # НОМЕРОМ КП из схемы нумерации продавца («КП-2026-00042_v1.pdf»), а не внутренним
        # deal-id/ИНН. Черновик без номера деградирует в старую deal-схему (уникальность цела).
        from crm.services.documents import quote_pdf_filename

        save_rendered_pdf(quote, quote_pdf_filename(quote), ContentFile(pdf_file.getvalue()))

        return quote

    @staticmethod
    @transaction.atomic
    def send_to_client(quote_id: int, sent_by_user, justification: str = "") -> Quote:
        """
        Send quote to client:
        1. Guard: only READY_TO_SEND (internally approved) quotes can be sent
        2. Generate PDF if not exists
        3. Set frozen_at timestamp
        4. Change status to SENT
        5. Change deal stage to QUOTE_SENT via FSM
        6. Create notification for client

        S7a below-floor guardrail: when the КП's gross margin is below the company
        margin FLOOR (economics.below_floor), a non-empty ``justification`` is REQUIRED
        (does NOT block the send — self-approve stays, DealHub standard) and is recorded
        on the counterparty timeline as a ``quote.sent_below_floor`` audit event. Above the
        floor no justification is required and no special event is logged.
        """
        from django.utils import timezone

        quote = Quote.objects.select_related(
            "deal__company", "deal__client", "deal__contact", "deal__stage", "status"
        ).get(pk=quote_id)

        # Send preconditions (status / recipient / claim) — the
        # full guard rationale lives in lifecycle_gates.assert_sendable. Returns the issuing
        # seller company (used for КП-number minting below).
        seller_company = assert_sendable(quote, sent_by_user)

        # Economics + below-floor guardrail. compute_quote_economics is resolved via THIS
        # module's global so the below-floor send tests can patch it.
        justification = (justification or "").strip()
        economics = compute_quote_economics(quote)
        assert_send_economics(quote, economics, justification)
        below_floor = bool(economics["below_floor"])

        # Mint the public no-login access token once (idempotent across re-sends of the
        # same КП version). Lets an offline/registered client open the client projection
        # without an account; rotate only by issuing a new version.
        import secrets

        if not quote.public_access_token:
            quote.public_access_token = secrets.token_urlsafe(32)

        # Mint a human, sequential, quotable КП number on first send (idempotent across
        # re-sends of the same version) — world-standard B2B: every offer the buyer receives
        # carries a citable document number, per-company-prefixed (ACME-КП-2026-00001) or the
        # shared platform counter (КП-2026-00001). Re-using next_document_number keeps the КП
        # consistent with Contract/Invoice/Act numbering.
        if not quote.number:
            from crm.services.numbering import next_document_number

            quote.number = next_document_number("KP", "КП", seller_company)

        # Default offer validity (Odoo Default Validity): a sent КП should carry an expiry. If
        # valid_until is still unset and the ISSUING company configured default_offer_validity_days,
        # populate it now — the create-time pre-fill may not have run, or the setting was added
        # later. Left None when the company hasn't configured a default (open-ended, today's public
        # link behaviour). seller_company is None on a superuser/platform send → no validity.
        from crm.services.quotes.access import compute_default_valid_until

        validity_fields = []
        if quote.valid_until is None:
            default_valid_until = compute_default_valid_until(seller_company)
            if default_valid_until is not None:
                quote.valid_until = default_valid_until
                validity_fields.append("valid_until")

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code=QuoteStatusCode.SENT).first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        # Drop any cached pre-send render. A «Предпросмотр PDF» seconds before sending caches a
        # DRAFT PDF («ЧЕРНОВИК» stamp, placeholder number «{deal}-{v}») — and send_quote_email
        # only renders when pdf_file is EMPTY, so that stale draft would be emailed to the client
        # and served on the public link (prod incident 2026-07-26: КП RFQ-0726RT-01 delivered as
        # «КП № 27-1 / ЧЕРНОВИК»). The send re-mints the document identity (№, frozen prices), so
        # the cache is wrong by construction. Blank the field only (file stays in storage —
        # same non-transactional-delete caution as _invalidate_branded_pdfs).
        quote.pdf_file = ""
        quote.save(
            update_fields=[
                "status",
                "number",
                "frozen_at",
                "public_access_token",
                "pdf_file",
                *validity_fields,
                "updated_at",
            ]
        )

        # AI-калибровка: the sent КП is the ground truth for the draft's AI match candidates.
        from crm.services.ai_telemetry import finalize_outcomes_on_send

        finalize_outcomes_on_send(quote)

        # Номенклатура, волна A: строки БЕЗ товара уходят в очередь кандидатов продавца вместе с
        # тем, что он в них заполнил (ТН ВЭД, ГОСТ, артикул, единица) — до этого знание умирало
        # вместе с КП, и 92% строк шли мимо каталога. Момент выбран как у Ariba catalog
        # enablement: в очередь попадает ОТПРАВЛЕННЫЙ документ, а не заготовка, которую продавец
        # ещё крутит. Сбор никогда не роняет отправку (см. `capture_quote_lines`).
        from catalog.candidates import capture_quote_lines

        capture_quote_lines(quote)

        # Counterparty timeline events (see lifecycle_audit): the plain send, plus a separate
        # first-class below-floor event carrying the seller's written justification.
        lifecycle_audit.log_quote_sent(quote, sent_by_user)
        if below_floor:
            lifecycle_audit.log_below_floor_send(quote, sent_by_user, justification, economics)

        # Email the КП off the request thread, after commit (F1.6 — no render inside the
        # atomic block, no orphan on rollback). The task renders the PDF if needed, then
        # emails it (with the public link) to the recipient — registered client OR offline
        # contact. Unified send: one action, channel adapts to who the recipient is.
        from crm.tasks import send_quote_email

        transaction.on_commit(lambda: send_quote_email.delay(quote_id))

        # Change deal stage via FSM. P0-1: the real buyer path lands the deal in RFQ_OPEN, and
        # QUOTE_SENT is only legal from CALCULATING — so advance through CALCULATING first, and
        # CAPTURE the error instead of swallowing it. Previously the error was discarded: the КП
        # was marked SENT + emailed while the deal silently stayed in RFQ_OPEN forever (dead-end).
        deal = quote.deal
        current_stage = deal.stage.code if deal.stage else None
        if current_stage in (DealStageCode.RFQ_OPEN, DealStageCode.SOURCING):
            _, stage_err = transition_deal_stage(
                deal, DealStageCode.CALCULATING, actor=sent_by_user, reason="Сборка КП к отправке"
            )
            if stage_err:
                raise ValueError(stage_err)
        _, stage_err = transition_deal_stage(
            deal,
            DealStageCode.QUOTE_SENT,
            actor=sent_by_user,
            reason=f"КП v{quote.version} отправлено клиенту",
        )
        if stage_err:
            raise ValueError(stage_err)

        # Create notification for the client contact (see lifecycle_audit).
        lifecycle_audit.notify_client_new_quote(quote)

        return quote

    @staticmethod
    def approve_quote(quote_id: int, approved_by_user) -> Quote:
        """Registered buyer accepts the КП. Only SENT quotes can be approved.

        Thin wrapper over the shared acceptance core (Rule 8) — the offline-contact path
        (``accept_quote_as_contact``) reuses the exact same FSM + contract + notification.
        """
        from .lifecycle_accept import perform_quote_acceptance

        return perform_quote_acceptance(quote_id, approved_by_user=approved_by_user)

    @staticmethod
    def accept_quote_as_contact(quote_id: int, *, contact_email: str, request_ip: str = "") -> Quote:
        """Offline contact accepts the КП after email-code verification (Wave A).

        No ``CustomUser`` exists for an offline contact, so ``approved_by`` stays NULL; the
        contact's email + request IP are recorded on the timeline audit. Same FSM / contract /
        seller-notification path as the registered-buyer accept. Commercial acceptance
        (коммерческий акцепт) with an audit trail — NOT a qualified e-signature.
        """
        from .lifecycle_accept import perform_quote_acceptance

        return perform_quote_acceptance(
            quote_id, approved_by_user=None, contact_email=contact_email, request_ip=request_ip
        )

    @staticmethod
    def revoke_public_link(quote_id: int, actor: CustomUser) -> Quote:
        """Seller revokes the public no-login link (Wave B post-send panel).

        Idempotent: sets ``public_token_revoked=True`` so ``public_quote_gate`` returns
        QUOTE_LINK_REVOKED (410) on any further open. The 256-bit token itself is NOT rotated
        (re-sending the same КП version keeps its citable number/link); a fresh link is minted by
        issuing a new version. Records a timeline event so the audit shows who pulled the link.
        """
        from ._shared import _log_quote

        quote = Quote.objects.select_related("deal", "status").get(pk=quote_id)
        if not quote.public_token_revoked:
            quote.public_token_revoked = True
            quote.save(update_fields=["public_token_revoked", "updated_at"])
            _log_quote(
                quote,
                actor,
                "Публичная ссылка отозвана",
                f"КП v{quote.version} ({quote.number or '—'})",
                event_code="quote.link_revoked",
                event_params={"version": quote.version},
            )
        return quote

    # ── Internal approval chain (документооборот) ──────────────────────────
    # DRAFT → PENDING_TRADE_REVIEW → PENDING_APPROVAL → READY_TO_SEND → (send).
    # Each step is gated by the actor's WorkspaceRole in the company that owns the
    # КП (the preparer's company); OWNER may act on any step. Returns
    # (quote, None) on success or (None, error_code) for views to map to HTTP.

    @staticmethod
    @transaction.atomic
    def submit_for_review(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """Sales submits a built КП into the chain. DRAFT → PENDING_TRADE_REVIEW,
        or straight to PENDING_APPROVAL if the company has no ВЭД member."""
        quote = Quote.objects.select_related("status", "prepared_by", "deal").get(pk=quote_id)

        # Resolve the КП-owning company WITHOUT mutating anything (audit F0) and gate the
        # approval-chain ENTRY on the quote.build CompanyRole permission — see
        # lifecycle_gates.resolve_submit_company for the full F0/H2 + ADR-0005 rationale.
        company_id, err = resolve_submit_company(quote, actor)
        if err:
            return None, err

        # M1-ERP-08 «курс на дату КП»: живой черновик пересчитывается по курсу на сегодня ДО гейтов —
        # согласующий видит ровно те суммы, что уйдут клиенту (курс фиксируется ниже, после гейтов).
        from sales.services.quote_fx import fix_quote_rates, live_rates_outdated

        if live_rates_outdated(quote):
            from .pricing import QuoteCalculationService

            QuoteCalculationService.recalculate_quote(quote.pk)
            quote.refresh_from_db()

        # Status + value + loss-prevention gate (see lifecycle_gates.assert_submittable).
        # compute_quote_economics is resolved via this module's global and reused for the
        # approval-chain build below.
        economics = compute_quote_economics(quote)
        err = assert_submittable(quote, economics)
        if err:
            return None, err

        # All gates passed — NOW it is safe to claim the КП: anchor BOTH the preparer and the
        # owning seller company to the VERIFIED company resolved above (audit F0/H2), so the
        # rest of the chain, the document header and the КП number all resolve to ONE coherent
        # company — never "validated against routed B but anchored to primary A".
        claim_fields = []
        if not quote.prepared_by_id:
            quote.prepared_by = actor
            claim_fields.append("prepared_by")
        if not quote.seller_company_id:
            quote.seller_company_id = company_id
            claim_fields.append("seller_company")
        if claim_fields:
            quote.save(update_fields=[*claim_fields, "updated_at"])
        # ATP auto-split (Track B): the КП is built and leaving DRAFT — split every
        # product line whose seller stock can't cover the requested qty into наличие +
        # под заказ tranches, in one pass (no per-line clicks). Idempotent: an already-
        # split set is left alone, so re-submitting after a send-back never re-splits.
        from crm.services.availability import auto_split_quote_by_availability

        auto_split_quote_by_availability(quote, company_id)
        # Unified approval workflow: build the permission-driven step list (mandatory head +
        # optional reviewer(s) + risk-aware reason), then route. Source of truth = the steps,
        # not a granular status — the КП goes to a single «На согласовании» (PENDING_APPROVAL).
        from crm.services.approvals import _active_order, _notify_order, auto_approve_solo_chain, build_approval_chain

        build_approval_chain(quote, company_id, economics=economics)
        _set_quote_status(quote, QuoteStatusCode.PENDING_APPROVAL)
        # Курсы фиксируются при выходе из черновика (после смены статуса: пересчёт черновика их бы
        # снова сделал живыми). Дальше пересчёт берёт курс только из снимка КП.
        fix_quote_rates(quote, actor)

        # Salesforce «no approval rule triggered / only approver is the submitter» pattern: when
        # every step of the freshly-built chain is assigned to the submitter themselves (a solo
        # company, or the company admin submitting their own КП), auto-approve instantly →
        # READY_TO_SEND, with an audited «согласовано автоматически» journal event. A genuine
        # cross-person chain (a different head, a ВЭД reviewer, a below-floor escalation to
        # someone else) is untouched and routes exactly as today. Removes ritual, not control —
        # the below-floor justification gate still fires at send.
        if auto_approve_solo_chain(quote, actor):
            quote.refresh_from_db()
            return quote, None

        first_order = _active_order(quote)
        if first_order is not None:
            _notify_order(quote, first_order)
        _log_quote(
            quote,
            actor,
            "КП отправлен на согласование",
            f"КП v{quote.version} на согласование (цепочка построена)",
            event_code="quote.submitted_for_review",
            event_params={"version": quote.version},
        )
        return quote, None

    @staticmethod
    @transaction.atomic
    def force_approve_quote(
        quote_id: int,
        admin_user: CustomUser,
        reason: str = "",
    ) -> Tuple[Optional[Quote], Optional[str]]:
        """Platform-admin force override: approve a quote regardless of its current status.

        Used for escalations (e.g. client unreachable but verbally approved offline).
        Logged with [FORCE_ADMIN] marker so audit can distinguish from normal flow.
        Caller must have SystemRole.ADMIN or be is_superuser. Viewer-mode admins
        (ADMIN without a CompanyMember) are explicitly permitted — force-actions
        are platform-admin moderation, not bound to membership.
        """
        from django.utils import timezone

        # Каноничный предикат вместо ручной сборки того же условия. Он СТРОЖЕ на одну деталь:
        # дополнительно требует отсутствия активных членств у носителя SystemRole=ADMIN. Это и
        # есть инвариант ADR-0003 («оператор платформы не бывает CompanyMember»), который
        # миграция accounts/0010 обеспечивает на данных, — так что на реальных пользователях
        # результат тот же, а расхождение, если оно когда-нибудь возникнет, теперь закрывается
        # отказом, а не тихим допуском.
        if not getattr(admin_user, "is_superuser", False):
            return None, "PLATFORM_ADMIN_REQUIRED"
        if not reason.strip():
            return None, "FORCE_REASON_REQUIRED"
        # of=("self",): Quote.status is a nullable FK, so select_related("status")
        # emits a LEFT OUTER JOIN, and Postgres rejects "FOR UPDATE" on the nullable
        # side of an outer join. Lock only the crm_quote row, not the joined tables.
        quote = Quote.objects.select_for_update(of=("self",)).select_related("deal", "status").get(pk=quote_id)
        approved = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
        if not approved:
            return None, "QUOTE_STATUS_NOT_FOUND"
        old_code = quote.status.code if quote.status else "None"
        quote.status = approved
        quote.approved_at = timezone.now()
        quote.approved_by = admin_user
        # LEAK FIX: the force-override reason + the platform-admin EMAIL must NOT land in
        # quote.notes — that field is rendered verbatim in the CLIENT КП PDF «Примечания». The
        # override is fully captured below in the entity-scoped audit log (log_admin_action).
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        # Structured, entity-scoped audit (G2 Gap A) — route through log_admin_action like
        # transition_deal_stage, so the override carries reason + entity_type/id + before/after
        # and shows on the quote timeline and the «Журнал доступа» page (not a bare ActivityLog).
        log_admin_action(
            entity_type="quote",
            entity_id=quote_id,
            action="[FORCE_ADMIN] КП одобрено платформенным админом",
            detail=f"КП #{quote_id} ({old_code} → APPROVED).",
            event_code="quote.approved_force",
            event_params={"quote_id": quote_id, "from_status": old_code},
            actor=admin_user,
            reason=reason,
            before={"status": old_code},
            after={"status": QuoteStatusCode.APPROVED},
            level="WARNING",
        )
        return quote, None

    @staticmethod
    def reject_quote(quote_id: int, rejected_by_user, reason: str = "") -> Quote:
        """Registered buyer rejects the КП. Only SENT quotes can be rejected.

        Thin wrapper over the shared rejection core (Rule 8); the offline-contact path
        (``reject_quote_as_contact``) reuses the exact same FSM + notification.
        """
        from .lifecycle_accept import perform_quote_rejection

        return perform_quote_rejection(quote_id, rejected_by_user=rejected_by_user, reason=reason)

    @staticmethod
    def reject_quote_as_contact(quote_id: int, *, reason: str, contact_email: str = "", request_ip: str = "") -> Quote:
        """Offline contact rejects the КП from the public page (Wave A) — required reason.

        Reject is recoverable (deal returns to CALCULATING; the seller can re-send), so it is
        gated only by possession of the 256-bit public link + a required reason, not the email
        code. Same FSM / seller-notification path as the registered-buyer reject.
        """
        from .lifecycle_accept import perform_quote_rejection

        return perform_quote_rejection(
            quote_id, rejected_by_user=None, reason=reason, contact_email=contact_email, request_ip=request_ip
        )
