"""Non-delivery reports (DSN, RFC 3464) arriving in the shared mailbox: recognition and parsing.

Pure functions without I/O. A bounce is a machine reply of a mail server to a message WE sent: it
must never become a lead or a normal «Входящие» item; it is linked to the outgoing message and
marks the failed address. `parse_bounce` returns `None` for an ordinary letter.

Recognition (any of): `multipart/report; report-type=delivery-status`; a `message/delivery-status`
part; the sender `mailer-daemon` / `postmaster` together with an `X-Failed-Recipients` header or a
status code in the text. Positive reports (`Action: delivered|relayed|expanded|delayed`-less) are
not bounces. Severity: `5.x.x` (or `Action: failed` without a code) is permanent, `4.x.x` and
`Action: delayed` are soft.
"""

import re
from dataclasses import dataclass
from email import message_from_bytes, message_from_string, policy
from email.message import EmailMessage, Message
from email.utils import getaddresses
from typing import Final, Literal

Severity = Literal["permanent", "soft"]
#: Plain-words reason codes; the Platform maps them to texts (ru/en/uz).
Reason = Literal["domain_not_found", "mailbox_not_found", "mailbox_full", "rejected", "other"]

_MAX_DIAGNOSTIC: Final = 500
# Hostile input bounds: header values and text are cut before any regular expression runs.
_MAX_VALUE: Final = 1000
_MAX_TEXT: Final = 64 * 1024
_MAX_GROUPS: Final = 50
_MAX_PARTS: Final = 200
_AUTO_SENDERS: Final = ("mailer-daemon", "postmaster")
_STATUS: Final = re.compile(r"(?<![\d.])([245])\.(\d{1,3})\.(\d{1,3})(?![\d.])")
_ADDRESS: Final = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
_ANGLE_ID: Final = re.compile(r"<([^<>\s]+)>")
_TEXT_ID: Final = re.compile(r"Message-ID:\s*<([^<>\s]+)>", re.IGNORECASE)

_DOMAIN: Final = re.compile(
    r"domain name not found|host not found|no such domain|nxdomain|domain not found|"
    r"name service error|domain does not exist|domain .{0,40}(?:not exist|invalid)|"
    r"unrouteable address|no mx|unknown host|host or domain name not found|"
    r"домен.{0,30}(?:не найден|не существует)",
    re.IGNORECASE,
)
_MAILBOX: Final = re.compile(
    r"user unknown|no such user|unknown user|mailbox (?:not found|unavailable|does not exist|"
    r"doesn't exist)|recipient (?:address )?rejected|does not exist|account .{0,30}(?:disabled|"
    r"not exist)|invalid (?:mailbox|recipient)|no mailbox here|"
    r"пользователь.{0,30}не найден|ящик.{0,30}не существует",
    re.IGNORECASE,
)
_FULL: Final = re.compile(r"over quota|mailbox (?:is )?full|quota exceeded|storage", re.IGNORECASE)
_REJECTED: Final = re.compile(
    r"spam|blocked|blacklist|policy|not allowed|denied|reputation|dmarc|spf", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Bounce:
    """What a delivery report says: which address failed, how badly, why, about which letter."""

    recipients: tuple[str, ...]
    severity: Severity
    reason: Reason
    status: str | None  # enhanced status code "5.1.2"; None — the report has none
    diagnostic: str
    original_message_id: str | None  # Message-ID of our letter from the attached copy or the text
    reply_ids: tuple[str, ...]  # In-Reply-To / References of the report itself
    is_report: bool = True  # a real multipart/report; False — recognised only by sender and text


def _sender_is_auto(message: EmailMessage) -> bool:
    addresses = getaddresses([str(message.get("From", ""))])
    return any(addr.lower().split("@")[0] in _AUTO_SENDERS for _, addr in addresses)


def _walk(message: Message) -> list[Message]:
    return list(message.walk())[:_MAX_PARTS]


def _status_groups(report: Message) -> list[Message]:
    """Per-recipient groups of a `message/delivery-status` part (RFC 3464 §2.1)."""
    payload = report.get_payload()
    if not isinstance(payload, list):
        return []
    return [m for m in payload if isinstance(m, Message)][:_MAX_GROUPS]


def _recipient(group: Message) -> str | None:
    for name in ("Final-Recipient", "Original-Recipient"):
        raw = str(group.get(name, "")).strip()[:_MAX_VALUE]
        if raw:
            _, _, value = raw.rpartition(";")
            found = _ADDRESS.search(value or raw)
            if found:
                return found.group(0).lower()
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:_MAX_DIAGNOSTIC]


def _original_id(parts: list[Message]) -> str | None:
    """Message-ID of our letter: from the attached `message/rfc822` or `text/rfc822-headers`."""
    for part in parts:
        kind = part.get_content_type()
        if kind == "message/rfc822":
            inner = part.get_payload()
            first = inner[0] if isinstance(inner, list) and inner else None
            found = (
                _ANGLE_ID.search(str(first.get("Message-ID", "")))
                if isinstance(first, Message)
                else None
            )
            if found:
                return found.group(1)
        elif kind in ("text/rfc822-headers", "text/rfc822"):
            payload = part.get_payload(decode=True)
            text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
            headers = message_from_string(text)
            found = _ANGLE_ID.search(str(headers.get("Message-ID", "")))
            if found:
                return found.group(1)
    return None


def _text_id(text: str) -> str | None:
    """Exim and some others quote our headers in the text part: «Message-ID: <…>»."""
    found = _TEXT_ID.search(text)
    return found.group(1) if found else None


def _text_of(parts: list[Message]) -> str:
    chunks: list[str] = []
    for part in parts:
        if part.get_content_type() == "text/plain" and not part.is_multipart():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                chunks.append(_decode(payload, part.get_content_charset()))
            if sum(map(len, chunks)) >= _MAX_TEXT:
                break
    return "\n".join(chunks)[:_MAX_TEXT]


def _decode(payload: bytes, charset: str | None) -> str:
    """Unknown or broken charsets (`unknown-8bit`, `x-bogus`) must not break a letter: utf-8."""
    try:
        return payload[:_MAX_TEXT].decode(charset or "utf-8", "replace")
    except (LookupError, UnicodeError):
        return payload[:_MAX_TEXT].decode("utf-8", "replace")


def classify_reason(status: str | None, text: str) -> Reason:
    """Plain-words reason from the diagnostic text first, then from the status code."""
    if _DOMAIN.search(text) or status in ("5.1.2", "5.4.4"):
        return "domain_not_found"
    if _FULL.search(text) or (status or "")[1:] == ".2.2":
        return "mailbox_full"
    if _MAILBOX.search(text) or status in ("5.1.1", "5.1.0", "5.1.6", "5.2.1"):
        return "mailbox_not_found"
    if (
        (status or "").startswith("5.7")
        or (status or "").startswith("5.2.3")
        or _REJECTED.search(text)
    ):
        return "rejected"
    return "other"


def _first_status(*sources: str) -> str | None:
    for source in sources:
        found = _STATUS.search(source)
        if found:
            return f"{found.group(1)}.{found.group(2)}.{found.group(3)}"
    return None


def _is_report(message: EmailMessage, parts: list[Message]) -> bool:
    if message.get_content_type() == "multipart/report":
        kind = str(message.get_param("report-type") or "").lower()
        return kind in ("", "delivery-status")
    return any(p.get_content_type() == "message/delivery-status" for p in parts)


def parse_bounce(raw: bytes) -> Bounce | None:
    """`Bounce` for a delivery status notification, `None` for any other letter."""
    message = message_from_bytes(raw, policy=policy.default)
    if not isinstance(message, EmailMessage):
        return None
    parts = _walk(message)
    report = _is_report(message, parts)
    text = _text_of(parts)
    failed_header = str(message.get("X-Failed-Recipients", ""))[: _MAX_VALUE * 2]
    auto = _sender_is_auto(message)
    if not report and not (auto and (failed_header or _first_status(text) or _DOMAIN.search(text))):
        return None

    recipients: list[str] = []
    severity: Severity | None = None
    status: str | None = None
    diagnostic = ""
    delivered_only = report
    for part in parts:
        if part.get_content_type() != "message/delivery-status":
            continue
        for group in _status_groups(part):
            action = str(group.get("Action", "")).strip().lower()
            if action in ("delivered", "relayed", "expanded"):
                continue  # positive report: not a failure
            delivered_only = False
            address = _recipient(group)
            if address and address not in recipients:
                recipients.append(address)
            diag = str(group.get("Diagnostic-Code", ""))[:_MAX_VALUE]
            code = _first_status(str(group.get("Status", ""))[:_MAX_VALUE], diag)
            status = status or code
            diagnostic = diagnostic or _clean_text(diag)
            if action == "delayed" or (code or "").startswith("4"):
                severity = severity or "soft"
            elif action == "failed" or (code or "").startswith("5"):
                severity = "permanent"
    if (
        report
        and delivered_only
        and any(p.get_content_type() == "message/delivery-status" for p in parts)
    ):
        return None
    for _, addr in getaddresses([failed_header]):
        if addr and addr.lower() not in recipients:
            recipients.append(addr.lower())
    if not diagnostic:
        diagnostic = _clean_text(text)
    status = status or _first_status(text)
    if severity is None:
        severity = "soft" if (status or "").startswith("4") else "permanent"
    reply = tuple(
        dict.fromkeys(
            m.group(1)
            for name in ("In-Reply-To", "References")
            for m in _ANGLE_ID.finditer(str(message.get(name, "")))
        )
    )
    return Bounce(
        recipients=tuple(recipients),
        severity=severity,
        reason=classify_reason(status, f"{diagnostic} {text}"),
        status=status,
        diagnostic=diagnostic,
        original_message_id=_original_id(parts) or _text_id(text),
        is_report=report,
        reply_ids=reply,
    )
