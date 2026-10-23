"""Wave A — public КП page server-side actions (view telemetry + offline acceptance).

Rule 8: the public DRF views (``crm/views/quotes/public.py``) are thin — they resolve the quote
by token, run the reachability gate, and call ONE function here. All the business logic (view
dedup, one-time code issue/verify, contact acceptance/rejection) lives in this service.

Security posture (adversarial — see also ``crm/models/acceptance.py``):
  * View telemetry is fired by a browser BEACON, never the bare GET (email scanners pre-open
    links → false «viewed»). Deduped to the first genuine open (marker set once).
  * Acceptance is gated by a one-time, hashed, short-lived email code sent to the recipient
    resolved from the QUOTE'S OWN deal — never from request input (no enumeration / redirection).
  * A commercial acceptance (коммерческий акцепт) with an audit trail — NOT a qualified
    e-signature. The contract is still signed later via the existing MANUAL_MODE flow.
"""

import hashlib
import hmac
import logging
import secrets

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# One-time acceptance code parameters. Brute force over the 10^6 space is bounded by the attempt
# cap + short TTL + endpoint throttle + the 256-bit token already required to reach the quote.
CODE_TTL_MINUTES = 15
MAX_CODE_ATTEMPTS = 5
CODE_DIGITS = 6

# Rolling dedup: the view marker is set once (first genuine open). We do not re-notify on re-opens.
VIEW_DEDUP_HOURS = 6


def _hash_code(code: str) -> str:
    """sha256 hex of the plaintext code. The plaintext is NEVER stored — only this hash."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """A cryptographically-random zero-padded numeric code (easy to type from an email)."""
    upper = 10**CODE_DIGITS
    return str(secrets.randbelow(upper)).zfill(CODE_DIGITS)


def record_quote_view(quote, request_ip: str = "") -> bool:
    """Record the FIRST genuine (browser-beacon) open of the public КП page.

    Idempotent + race-safe: sets ``first_viewed_at`` once, and only then writes the
    ``quote.viewed`` timeline event + notifies the seller who built the КП. Re-opens are no-ops
    (no notification spam). Returns True iff this call recorded the first view.
    """
    from crm.models import Quote

    from .quotes._shared import _log_quote, _notify_quote_outcome, _quote_client_display_name

    with transaction.atomic():
        locked = Quote.objects.select_for_update(of=("self",)).select_related("deal", "status").get(pk=quote.pk)
        if locked.first_viewed_at is not None:
            return False
        locked.first_viewed_at = timezone.now()
        locked.save(update_fields=["first_viewed_at", "updated_at"])

        _log_quote(
            locked,
            None,
            "КП просмотрено клиентом",
            f"КП v{locked.version} ({locked.number or '—'})",
            event_code="quote.viewed",
            event_params={"version": locked.version, "number": locked.number or "—", "ip": request_ip or ""},
        )
        _notify_quote_outcome(
            locked,
            type_code="INFO",
            title="КП просмотрено клиентом",
            message=f"{_quote_client_display_name(locked)} открыл КП v{locked.version}",
            event_code="quote.viewed_by_client",
            event_params={"client": _quote_client_display_name(locked), "version": locked.version},
        )
        # Событие шины (rt_bus) — в транзакции отметки просмотра: сбой публикации откатывает и отметку.
        from integration.services import events

        events.publish_quote_outcome("quote.viewed", locked, actor={"type": "client"})
    return True


def _mint_acceptance_code(quote, email: str, request_ip: str = "", contact=None) -> str:
    """Выпустить одноразовый код (в базе только хеш) и погасить прежние неиспользованные — активен всегда один.

    `contact` — контакт Cabinet, которому выпущен код (Q-FIX22-6): погасить код сможет только он; публичная страница
    КП контакта не задаёт.
    """
    from crm.models import QuoteAcceptanceCode

    code = _generate_code()
    with transaction.atomic():
        # Single active code invariant: invalidate any prior unconsumed codes for this quote.
        QuoteAcceptanceCode.objects.filter(quote=quote, consumed_at__isnull=True).delete()
        QuoteAcceptanceCode.objects.create(
            quote=quote,
            contact=contact,
            email=email.strip().lower(),
            code_hash=_hash_code(code),
            expires_at=timezone.now() + timezone.timedelta(minutes=CODE_TTL_MINUTES),
            request_ip=request_ip or None,
        )
    return code


def issue_acceptance_code(quote, request_ip: str = "", *, contact=None, send=None) -> bool:
    """Mint + deliver a one-time acceptance code. Returns True when a code was minted and handed to delivery.

    Public page (``contact`` is None): the recipient is resolved from the QUOTE'S deal, never from request input.
    Enumeration-neutral: the caller ALWAYS returns the same neutral response; this function never signals whether a
    recipient exists. When the deal has no email recipient it simply no-ops.

    Cabinet (``contact`` is the portal session's contact, FIX-22): the code is issued FOR THAT CONTACT. By default it
    goes to the contact's e-mail (``EmailLog``); ``send(code)`` replaces the delivery (the portal uses it for the
    Telegram bot) and is called once, after the code is stored. A contact without an e-mail and without ``send``
    gets nothing (returns False).

    Any prior unconsumed code for this quote is dropped so only ONE code is ever active (keeps the per-code attempt
    cap meaningful).
    """
    from .quotes._shared import resolve_quote_recipient

    if contact is None:
        recipient = resolve_quote_recipient(quote)
        if recipient is None:
            return False  # no address on the deal → nothing to send (response stays neutral)
        email, _name = recipient
        language = None
    else:
        email = (contact.email or "").strip()
        language = contact.language
        if not email and send is None:
            return False

    code = _mint_acceptance_code(quote, email, request_ip, contact=contact)
    if send is not None:
        send(code)
    else:
        _send_code_email(quote, email, code, language=language)
    return True


def _send_code_email(quote, email: str, code: str, language=None) -> None:
    """Best-effort delivery of the acceptance code. A transport failure must NOT change the
    neutral public response, so it is logged and swallowed here (fail_silently)."""
    from notifications.emails import email_brand, send_templated_email

    seller_name = getattr(quote.seller_company, "name", None) or "Поставщик"
    deal_ref = quote.deal.title or f"#{quote.deal_id}"
    try:
        send_templated_email(
            "quote_acceptance_code",
            {
                "code": code,
                "quote_number": quote.number or f"{quote.deal_id}-{quote.version}",
                "seller_name": seller_name,
                "deal_ref": deal_ref,
                "expires_minutes": CODE_TTL_MINUTES,
                # D1e white-label: the seller's brand opens the email.
                **email_brand(quote.seller_company),
            },
            to=[email],
            channel="transactional",
            fail_silently=True,
            language=language,
        )
    except Exception:  # noqa: BLE001 — public endpoint: never surface a transport fault
        logger.exception("Acceptance-code email failed for quote %s", quote.pk)


def verify_code_and_accept(quote, code: str, request_ip: str = "", *, contact=None):
    """Verify a one-time code and, on success, accept the КП as the offline contact.

    `contact` — контакт сессии Cabinet (FIX-60a, Q-FIX22-6): код привязан к контакту, которому выпущен, и другой контакт
    той же компании его не погасит (`INVALID_CODE`, попытка кода не тратится). Публичная страница контакта не передаёт и
    гасит только коды без контакта (адрес сделки) — код Cabinet по ссылке КП не принимается.

    Returns ``(quote, None)`` on success or ``(None, ERROR_CODE)``. Fully atomic: the code is
    consumed and the acceptance is applied in ONE transaction — a failed accept persists nothing
    (the code is NOT burned). Adversarial bounds: single active code, constant-time hash compare,
    attempt cap, short TTL, single-use.
    """
    from crm.models import QuoteAcceptanceCode
    from crm.services.quotes import QuoteLifecycleService

    supplied = (code or "").strip()
    if not supplied:
        return None, "CODE_REQUIRED"

    with transaction.atomic():
        row = (
            QuoteAcceptanceCode.objects.select_for_update()
            .filter(quote=quote, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if row is None:
            return None, "NO_ACTIVE_CODE"
        if row.contact_id != (contact.pk if contact is not None else None):
            return None, "INVALID_CODE"  # чужой код: не погашаем и не жжём попытки владельца
        if row.expires_at < timezone.now():
            return None, "CODE_EXPIRED"
        if row.attempts >= MAX_CODE_ATTEMPTS:
            return None, "TOO_MANY_ATTEMPTS"
        # Constant-time compare of the sha256 hashes (never the plaintext).
        if not hmac.compare_digest(row.code_hash, _hash_code(supplied)):
            row.attempts += 1
            row.save(update_fields=["attempts"])
            return None, "INVALID_CODE"

        # Correct code → burn it and accept in the SAME transaction.
        row.consumed_at = timezone.now()
        row.save(update_fields=["consumed_at"])
        # Симметрично отказу: жизненный цикл кидает ValueError, если КП уже не SENT
        # (успели решить из другой вкладки). Отвечаем кодом, а не пятисоткой.
        try:
            accepted = QuoteLifecycleService.accept_quote_as_contact(
                quote.pk, contact_email=row.email, request_ip=request_ip or "", portal_contact=contact
            )
        except ValueError:
            return None, "QUOTE_ALREADY_DECIDED"

    if row.email:  # контакт только с Telegram письма не получает
        _send_accepted_next_step_email(accepted, row.email)
    return accepted, None


def _send_accepted_next_step_email(quote, email: str) -> None:
    """After a contact accepts, email them the «what's next» — the contract is ready to sign.
    Best-effort; a transport fault is logged, not surfaced (the page already shows success)."""
    from crm.models import Contract
    from notifications.emails import email_brand, send_templated_email

    contract = Contract.objects.filter(deal=quote.deal, quote=quote).order_by("-id").first()
    seller_name = getattr(quote.seller_company, "name", None) or "Поставщик"
    try:
        send_templated_email(
            "quote_accepted_contact",
            {
                "quote_number": quote.number or f"{quote.deal_id}-{quote.version}",
                "contract_number": getattr(contract, "number", "") or "—",
                "seller_name": seller_name,
                # D1e white-label: the seller's brand opens the email.
                **email_brand(quote.seller_company),
            },
            to=[email],
            channel="transactional",
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 — never surface a transport fault on the public path
        logger.exception("Accept next-step email failed for quote %s", quote.pk)


def reject_from_public_page(quote, reason: str, request_ip: str = ""):
    """Reject the КП from the public page — required reason. Returns ``(quote, None)`` or
    ``(None, ERROR_CODE)``. Recoverable (deal → CALCULATING), so gated by the link + reason only."""
    from crm.services.quotes import QuoteLifecycleService

    cleaned = (reason or "").strip()
    if not cleaned:
        return None, "REASON_REQUIRED"
    # Решение по КП уже принято — отвечаем КОДОМ, а не падаем. Жизненный цикл кидает
    # ValueError на любом статусе кроме SENT, и до 14-08 он улетал наружу пятисоткой:
    # клиент, принявший предложение, видел в той же сессии кнопку «Отклонить» (страница
    # дорисовывала успех, не убирая панель действий) и ловил ошибку сервера. Ловим
    # исключение, а не проверяем статус заранее: между проверкой и вызовом остаётся окно
    # гонки — два клика из двух вкладок.
    # O1: кто вернул КП — в журнал. Ссылку могли переслать, кода на этом действии нет (оно
    # обратимо, как reject в Odoo), поэтому единственная защита — СЛЕД: e-mail получателя,
    # которому мы отправляли ссылку, и IP запроса. Без него в ленте было «КП отклонено» без
    # единой зацепки, кто это сделал.
    from crm.services.quotes._shared import resolve_quote_recipient

    recipient = resolve_quote_recipient(quote)
    try:
        rejected = QuoteLifecycleService.reject_quote_as_contact(
            quote.pk, reason=cleaned, contact_email=recipient[0] if recipient else "", request_ip=request_ip or ""
        )
    except ValueError:
        return None, "QUOTE_ALREADY_DECIDED"
    return rejected, None
