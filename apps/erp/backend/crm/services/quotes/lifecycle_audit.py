"""КП lifecycle AUDIT / side-effect helpers — the timeline events and client notification
emitted when a КП is sent.

Split out of ``lifecycle.py`` (DT3 file-length split) — behaviour unchanged, code moved
not rewritten. These write ActivityLog timeline rows and the client Notification; they run
INSIDE the caller's ``send_to_client`` transaction, after the КП is frozen + numbered, so
the side effects and the state change commit atomically together (Rule 8 — business logic
stays in services).
"""

from ._shared import _log_quote


def log_quote_sent(quote, sent_by_user) -> None:
    """Counterparty timeline (Phase A): the send was only visible as a stage flip before —
    record it as a first-class event on the client's history."""
    _log_quote(
        quote,
        sent_by_user,
        "КП отправлено клиенту",
        f"КП v{quote.version} ({quote.number})",
        event_code="quote.sent",
        event_params={"version": quote.version, "number": quote.number},
    )


def log_below_floor_send(quote, sent_by_user, justification, economics) -> None:
    """S7a: separate, first-class audit event when the offer went out below the margin floor —
    captures the seller's written justification so the below-floor decision is traceable."""
    _log_quote(
        quote,
        sent_by_user,
        "КП отправлено ниже минимальной маржи",
        justification,
        event_code="quote.sent_below_floor",
        event_params={
            "version": quote.version,
            "number": quote.number,
            "margin_percent": str(economics["gross_margin_percent"]),
            "floor_percent": str(economics["min_margin_percent"]),
            "justification": justification,
        },
    )


def notify_client_new_quote(quote) -> None:
    """Create the buyer-facing notification for a freshly sent КП (registered client only).

    N2: name the SENDER + deal + the next action, so the client sees WHAT arrived, from
    WHOM, and what to do — not a status line with no context.
    """
    from notifications.models import Notification, NotificationType

    if not quote.deal.client:
        return
    info_type = NotificationType.objects.filter(code="INFO").first()
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
        event_code="quote.received",
        event_params={"seller": seller_name, "version": quote.version, "deal_ref": deal_ref},
    )
