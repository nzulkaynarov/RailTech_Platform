"""КП lifecycle state machine — render/send/approve/reject/submit/force-approve.

Split out of the monolithic ``crm/services/quotes.py`` (ARCH refactor) — behaviour
unchanged. NOTE (file-length exception): ``QuoteLifecycleService`` is a single cohesive
transactional state-machine class (~500 lines). Per the project's file-split rule, a
single class that is physically >500 lines may stay intact when splitting it across
modules would harm readability — that applies here (the methods share the same guard
vocabulary and FSM invariants), so the class is kept whole rather than fractured into
render/approval mixins. Depends on the leaf ``_shared`` helpers and ``pricing`` only.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction

from accounts.constants import SystemRoleCode
from accounts.models import CustomUser
from accounts.services.permissions import routed_seller_company_id
from core.audit import log_admin_action
from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import Quote, QuoteStatus
from crm.services.deals import transition_deal_stage

from ._shared import (
    _log_quote,
    _notify_quote_outcome,
    _quote_owner_company_id,
    _quote_seller_company,
    _set_quote_status,
    resolve_quote_recipient,
)
from .pricing import compute_quote_economics

logger = logging.getLogger(__name__)

# S7a (DealHub margin-floor guardrail): the free-text justification required when a КП is
# sent BELOW the company margin floor. Capped so it can't be abused as a free-text dump.
BELOW_FLOOR_JUSTIFICATION_MAX_LEN = 500


class QuoteLifecycleService:
    """Manages Quote state transitions: generate PDF, send, approve, reject."""

    @staticmethod
    def _assert_renderable(quote: Quote):
        """КП render guards; returns the issuing seller company.

        - An unclaimed buyer-request КП (prepared_by NULL) has NO issuing seller, so
          rendering it would brand a "коммерческое предложение" with the platform
          identity ("RailTech B2B") — misrepresenting the supplier on a commercial
          document (audit F1) → QUOTE_NOT_CLAIMED.
        - HOLE 2 (loss-prevention): the render/export surface was the gate bypass — a
          seller could generate a КП PDF on a DRAFT at the placeholder rate 1 (or below
          cost) and hand it to the client out-of-band, never touching submit/send.
          Refuse a client document whose numbers are wrong (no FX rate) or loss-making —
          the same gate as send_to_client.
        """
        seller_company = _quote_seller_company(quote)
        if seller_company is None:
            raise ValueError("QUOTE_NOT_CLAIMED")
        economics = compute_quote_economics(quote)
        if economics["fx_missing"]:
            raise ValueError("FX_RATE_MISSING")
        if economics["below_cost"]:
            raise ValueError("QUOTE_BELOW_COST")
        return seller_company

    @staticmethod
    def assert_pdf_renderable(quote_id: int) -> None:
        """Run the КП render guards WITHOUT rendering (ARCH-03).

        Views call this to surface the 409 guard errors synchronously while the
        WeasyPrint render itself happens off-thread in crm.tasks.render_document_pdf.
        """
        quote = Quote.objects.select_related("deal__company", "prepared_by").prefetch_related("items").get(pk=quote_id)
        QuoteLifecycleService._assert_renderable(quote)

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

        seller_company = QuoteLifecycleService._assert_renderable(quote)
        # Shared branding bundle (issuing company + its document profile + logo) — the same
        # shape every document feeds the base template. Watermark «ДЕМО» whenever the seller
        # cannot commercially SEND this КП (explicit DEMO grant, no operational subscription,
        # OR — ADR-0006 Phase E — no KYC). Building/previewing stays free; only a fully verified
        # + subscribed seller gets a clean, sendable document.
        from accounts.services.entitlements import quote_send_entitled
        from crm.services.documents import (
            client_optional_items,
            client_projection_items,
            document_brand_context,
            public_quote_qr,
            public_quote_url,
        )

        html_string = render_to_string(
            "crm/quote_pdf.html",
            {
                "quote": quote,
                # Client projection: charges distributed into per-line delivered prices (no
                # goods-vs-charges breakout — confidentiality). Lines sum to quote.total_excl_vat.
                # Includes SECTION/NOTE rows (display_type) in position order; optional lines are
                # rendered separately below the totals via `optional_items` (off-total offer).
                "items": client_projection_items(quote),
                "optional_items": client_optional_items(quote),
                "company": quote.deal.company,
                # Public «Принять онлайн» link + QR — present only after send (token minted), so the
                # seller-facing draft PDF has no CTA while the sent/public КП does (F-09).
                "public_quote_url": public_quote_url(quote),
                "public_quote_qr": public_quote_qr(quote),
                **document_brand_context(seller_company, is_demo=not quote_send_entitled(seller_company.id)),
            },
        )

        pdf_file = BytesIO()
        HTML(string=html_string).write_pdf(pdf_file)

        filename = f"KP_{quote.deal.company.inn}_{quote.deal_id}_v{quote.version}.pdf"
        quote.pdf_file.save(filename, ContentFile(pdf_file.getvalue()), save=True)

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

        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related(
            "deal__company", "deal__client", "deal__contact", "deal__stage", "status"
        ).get(pk=quote_id)

        # Status guard: only an internally-approved КП (READY_TO_SEND — it passed
        # the sales → ВЭД → director chain) may go out to the client.
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.READY_TO_SEND:
            raise ValueError(
                f"Cannot send quote in status '{current}'. "
                "Only READY_TO_SEND quotes (internally approved) can be sent to the client."
            )

        # RECIPIENT GATE (B5): a КП with nobody to send it to must not be marked SENT. The async
        # email task used to log a warning and return `no_recipient` while the КП was already
        # frozen + SENT and the deal moved to QUOTE_SENT — «отправлено в никуда», invisible to the
        # seller. Synchronous and BEFORE any state change, using the SAME resolver the task uses,
        # so the two can never disagree about what "has a recipient" means.
        if resolve_quote_recipient(quote) is None:
            raise ValueError("RECIPIENT_REQUIRED")

        # An unclaimed КП has no issuing seller (e.g. the preparer's membership was deactivated
        # after the КП was claimed) — refuse to send rather than freeze it under the PLATFORM
        # identity, mint a platform-branded number, and then have the async PDF render fail
        # (audit M2). Mirrors the generate_pdf QUOTE_NOT_CLAIMED guard so the failure surfaces
        # synchronously to the sender. A superuser send is the platform-escalation/orchestrator
        # path (no company membership by design) and is allowed through with platform branding.
        seller_company = _quote_seller_company(quote)
        if seller_company is None and not getattr(sent_by_user, "is_superuser", False):
            raise ValueError("QUOTE_NOT_CLAIMED")

        # SELLER FLOOR (ADR-0006 Phase E): «без KYC только демо». A seller must be KYC-verified (L2+)
        # to send a real КП — checked first so an unverified seller gets a clear "do KYC" message
        # rather than a generic billing error. Then the MONETIZATION GATE (Move 4): sending is a PAID
        # action needing the quote.send entitlement (an operational subscription grants it). A
        # demo/unsubscribed seller can build the КП but not send it. Superuser = platform escalation.
        if seller_company is not None and not getattr(sent_by_user, "is_superuser", False):
            from accounts.services import quote_send_entitled
            from accounts.services.kyc import company_kyc_verified

            if not company_kyc_verified(seller_company.id):
                raise ValueError("SELLER_KYC_REQUIRED")
            if not quote_send_entitled(seller_company.id):
                raise ValueError("QUOTE_SEND_NOT_ENTITLED")

        # LOSS PREVENTION (authoritative server gate): never send a КП priced below its landed
        # cost — even if items/charges were edited after the internal approval. Mirrors the
        # live G1 guardrail in the builder; can't be bypassed via the API.
        # A value-less КП (no priced lines) must not go to the client even if it carries charges
        # (HOLE 4 — submit had this guard, send did not; items can change after READY_TO_SEND).
        if (quote.subtotal_excl_vat or 0) <= 0:
            raise ValueError("QUOTE_HAS_UNPRICED_LINES")
        _econ = compute_quote_economics(quote)
        if _econ["fx_missing"]:
            raise ValueError("FX_RATE_MISSING")
        if _econ["below_cost"]:
            raise ValueError("QUOTE_BELOW_COST")

        # BELOW-FLOOR GUARDRAIL (S7a, DealHub standard): sending a КП under the company margin
        # FLOOR is allowed (self-approve — NOT approval-routing, unlike the hard below_cost block)
        # but must carry a written justification that lands in the audit trail. Length-capped so it
        # can't be abused. Above-floor sends require nothing and log no special event. The gate is
        # server-authoritative: it fires even for a sender WITHOUT cost visibility (who never saw
        # below_floor on the client), so the SPA re-prompts on the error code.
        justification = (justification or "").strip()
        if len(justification) > BELOW_FLOOR_JUSTIFICATION_MAX_LEN:
            raise ValueError("JUSTIFICATION_TOO_LONG")
        below_floor = bool(_econ["below_floor"])
        if below_floor and not justification:
            raise ValueError("BELOW_FLOOR_JUSTIFICATION_REQUIRED")

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

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code=QuoteStatusCode.SENT).first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        quote.save(update_fields=["status", "number", "frozen_at", "public_access_token", "updated_at"])

        # AI-калибровка: the sent КП is the ground truth for the draft's AI match candidates.
        from crm.services.ai_telemetry import finalize_outcomes_on_send

        finalize_outcomes_on_send(quote)

        # Counterparty timeline (Phase A): the send was only visible as a stage flip before —
        # record it as a first-class event on the client's history.
        _log_quote(
            quote,
            sent_by_user,
            "КП отправлено клиенту",
            f"КП v{quote.version} ({quote.number})",
            event_code="quote.sent",
            event_params={"version": quote.version, "number": quote.number},
        )

        # S7a: separate, first-class audit event when the offer went out below the margin floor —
        # captures the seller's written justification so the below-floor decision is traceable.
        if below_floor:
            _log_quote(
                quote,
                sent_by_user,
                "КП отправлено ниже минимальной маржи",
                justification,
                event_code="quote.sent_below_floor",
                event_params={
                    "version": quote.version,
                    "number": quote.number,
                    "margin_percent": str(_econ["gross_margin_percent"]),
                    "floor_percent": str(_econ["min_margin_percent"]),
                    "justification": justification,
                },
            )

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

        # Create notification for client contact
        if quote.deal.client:
            info_type = NotificationType.objects.filter(code="INFO").first()
            # N2: name the SENDER + deal + the next action, so the client sees WHAT arrived, from
            # WHOM, and what to do — not a status line with no context.
            seller_name = getattr(quote.seller_company, "name", None) or "Поставщик"
            deal_ref = quote.deal.title or f"#{quote.deal_id}"
            Notification.objects.create(
                user=quote.deal.client,
                type=info_type,
                title="Новое КП от поставщика",
                message=f"«{seller_name}» отправил вам КП v{quote.version} по сделке «{deal_ref}» — "
                f"откройте, чтобы принять или отклонить.",
                link="/cabinet/deals",
                deal=quote.deal,
            )

        return quote

    @staticmethod
    @transaction.atomic
    def approve_quote(quote_id: int, approved_by_user) -> Quote:
        """Client approves the quote. Only SENT quotes can be approved."""
        from django.utils import timezone

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.SENT:
            raise ValueError(f"Cannot approve quote in status '{current}'. " "Only SENT quotes can be approved.")

        approved_status = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
        quote.status = approved_status
        quote.approved_at = timezone.now()
        quote.approved_by = approved_by_user
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

        # Change deal stage via FSM (P0-1: capture the error — don't swallow it).
        _, stage_err = transition_deal_stage(
            quote.deal,
            DealStageCode.CONTRACT_SIGNED,
            actor=approved_by_user,
            reason=f"КП v{quote.version} одобрено клиентом",
        )
        if stage_err:
            raise ValueError(stage_err)

        # Materialize the Contract the instant the buyer accepts — otherwise the deal sits in
        # CONTRACT_SIGNED with NO actual Contract (audit B1: approve → green badge → dead-end,
        # generate_contract_from_quote was only ever called from tests). actor=None = system
        # path: the buyer's approval triggers it, and the buyer is not a seller so it must NOT
        # go through the seller-actor guard. Best-effort — a render hiccup must not unwind the
        # approval (the seller can re-issue from the contract surface).
        from crm.services.contracts import generate_contract_from_quote

        try:
            generate_contract_from_quote(quote.id, actor=None)
        except (ValueError, OSError) as exc:  # noqa: BLE001 — narrow: lookup/PDF render
            logger.warning("Contract auto-generation after approval failed for quote %s: %s", quote.id, exc)

        # Notify the seller who built the КП (and a distinct manager, if assigned)
        # that the client approved. deal.manager is usually unset in the single-
        # seller model, so prepared_by is the reliable recipient — without it the
        # seller never learned the outcome. Pushed over WS for realtime delivery.
        _notify_quote_outcome(
            quote,
            type_code="SUCCESS",
            title="КП одобрено клиентом",
            message=f"{quote.deal.company.name} одобрил КП v{quote.version}",
        )

        # Counterparty timeline (Phase A): the acceptance itself was only visible as a stage
        # flip before — record it as a first-class event on the client's history.
        _log_quote(
            quote,
            approved_by_user,
            "КП принято клиентом",
            f"КП v{quote.version} ({quote.number or '—'})",
            event_code="quote.accepted",
            event_params={"version": quote.version, "number": quote.number or "—"},
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
        # Resolve the КП-owning company WITHOUT mutating anything first (audit F0):
        #   • already-claimed КП → the preparer's company;
        #   • unclaimed buyer-request КП → the submitter MAY claim it, but ONLY if they are
        #     a can_sell seller routed to THIS deal. Anchoring prepared_by before this check
        #     let any authenticated user (even a buyer) hijack the КП + drive its approval
        #     chain cross-tenant, and the write committed even on a rejected call.
        if quote.prepared_by_id:
            company_id = _quote_owner_company_id(quote)
            if not company_id:
                return None, "NO_QUOTE_COMPANY"
        else:
            company_id = routed_seller_company_id(actor, quote.deal_id)
            if not company_id:
                return None, "ROLE_NOT_PERMITTED"
        # ADR-0005 Phase E U3 Step 2: gate the approval-chain ENTRY on the quote.build CompanyRole
        # permission instead of the SALES_MANAGER WorkspaceRole — the ADR intent is "gate on the
        # capability, not the role title". Effective policy shift (intended, within-tenant only):
        #   • member WITH a CompanyRole → passes iff that role grants quote.build (an OWNER/SALES_MANAGER
        #     WorkspaceRole no longer overrides a restrictive CompanyRole — CompanyRole is authoritative);
        #   • company_role-less member → fallback: quote.build ∈ _SELL_PERMS → grants ANY can_sell member
        #     of the owning company (broader than the old SALES_MANAGER/OWNER-only gate, but same-tenant
        #     and capability-based; it collapses to precise once tenants are fully on CompanyRoles).
        # No buyer/cross-tenant leak (member_has_permission scopes to company_id; a can_sell=False buyer
        # is denied). Dev data-check: 0 of 13 active SALES_MANAGER/OWNER members lose submit. can_send
        # (the only NARROWING site) stays on WorkspaceRole until the Step-4 coverage migration.
        from accounts.services.permissions import member_has_permission

        if not member_has_permission(actor, company_id, "quote.build"):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.DRAFT:
            return None, "INVALID_STATUS"
        # A commercial offer cannot enter the approval chain with NO value: reject a КП whose
        # total is zero/negative (the "half-priced / unpriced КП" gap — it could otherwise be
        # approved and sent to the client at 0,00). Keyed on the КП TOTAL (not per-line) so a
        # deliberately-free line (included item, sample, 100% promo discount) among priced lines
        # is still allowed — only a genuinely value-less offer is blocked (audit M6).
        if (quote.subtotal_excl_vat or 0) <= 0:
            return None, "QUOTE_HAS_UNPRICED_LINES"
        # LOSS PREVENTION (hard stop): a КП whose client total is below its landed cost would be
        # sold at a loss — never allow it into the approval chain. Below the margin FLOOR is a
        # softer signal (warn + approval on the client side), NOT a hard block here.
        _econ = compute_quote_economics(quote)
        if _econ["fx_missing"]:
            return None, "FX_RATE_MISSING"
        if _econ["below_cost"]:
            return None, "QUOTE_BELOW_COST"
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
        from crm.services.approvals import _active_order, _notify_order, build_approval_chain

        build_approval_chain(quote, company_id, economics=_econ)
        _set_quote_status(quote, QuoteStatusCode.PENDING_APPROVAL)
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

        if not (
            getattr(admin_user, "is_superuser", False)
            or (admin_user.role and admin_user.role.code == SystemRoleCode.ADMIN)
        ):
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
    @transaction.atomic
    def reject_quote(quote_id: int, rejected_by_user, reason: str = "") -> Quote:
        """Client rejects the quote. Only SENT quotes can be rejected."""

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.SENT:
            raise ValueError(f"Cannot reject quote in status '{current}'. " "Only SENT quotes can be rejected.")

        rejected_status = QuoteStatus.objects.filter(code=QuoteStatusCode.REJECTED).first()
        quote.status = rejected_status
        # LEAK FIX: the rejection reason is NOT written to quote.notes (rendered in the client КП
        # PDF). It's preserved on the deal-stage transition audit below + the seller notification.
        quote.save(update_fields=["status", "updated_at"])

        # Move deal back to CALCULATING via FSM (P0-1: capture the error — don't swallow it).
        _, stage_err = transition_deal_stage(
            quote.deal,
            DealStageCode.CALCULATING,
            actor=rejected_by_user,
            reason=f"КП v{quote.version} отклонено. {reason}",
        )
        if stage_err:
            raise ValueError(stage_err)

        # Notify the КП author (+ distinct manager) that the client rejected —
        # same single-seller reasoning as approve_quote. Pushed over WS.
        _notify_quote_outcome(
            quote,
            type_code="WARNING",
            title="КП отклонено клиентом",
            message=f"{quote.deal.company.name} отклонил КП v{quote.version}. {reason}".strip(),
        )

        # Counterparty timeline (Phase A): first-class rejection event (the reason already
        # lives on the stage-transition audit row; keep the client-PDF leak fix intact).
        _log_quote(
            quote,
            rejected_by_user,
            "КП отклонено клиентом",
            f"КП v{quote.version}",
            event_code="quote.rejected",
            event_params={"version": quote.version},
        )

        return quote
