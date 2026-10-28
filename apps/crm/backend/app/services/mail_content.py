"""Тело письма, запрошенного другой системой по шине (W18A-P1, CONTRACTS §9): расшифровка.

ERP и EDS кладут текст, HTML и ссылки на вложения в `data.content` события
`uz.railtech.<домен>.mail.requested.v1` шифртекстом (`alg = fernet-pair-v1`), чтобы одноразовые
ссылки входа и приглашений не лежали открыто ни в outbox отправителя, ни в inbox CRM. Ключ —
`urlsafe_b64(HMAC-SHA256(секрет пары «<домен> → crm», "rt-mail/v1/content"))`: секрет пары обе
стороны уже знают (он же подписывает доставку, `app.bus.secrets`), отдельного ключа нет. Действующих
секретов может быть несколько (ротация): пробуется каждый.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

ALG: Final = "fernet-pair-v1"
_LABEL: Final = b"rt-mail/v1/content"


class ContentUnreadableError(Exception):
    """Шифртекст не открывается ни одним секретом пары или открытый текст не по формату."""


@dataclass(frozen=True, slots=True)
class MailLink:
    url: str
    expires_at: str | None


@dataclass(frozen=True, slots=True)
class MailContent:
    text: str
    html: str | None
    links: tuple[MailLink, ...]


def content_key(pair_secret: str) -> bytes:
    digest = hmac.new(pair_secret.encode("utf-8"), _LABEL, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest)


def seal(pair_secret: str, content: MailContent) -> str:
    """Обратная операция (тесты и образец для отправителей): JSON {text, html, links} → Fernet."""
    plain = {
        "text": content.text,
        "html": content.html,
        "links": [{"url": link.url, "expires_at": link.expires_at} for link in content.links],
    }
    raw = json.dumps(plain, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Fernet(content_key(pair_secret)).encrypt(raw).decode("ascii")


def open_content(alg: str, ciphertext: str, secrets: Iterable[str]) -> MailContent:
    if alg != ALG:
        raise ContentUnreadableError(f"unknown alg {alg!r}")
    try:
        token = ciphertext.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ContentUnreadableError("ciphertext is not ascii") from exc
    for secret in secrets:
        try:
            raw = Fernet(content_key(secret)).decrypt(token)
        except InvalidToken:
            continue
        return _parse(raw)
    raise ContentUnreadableError("no pair secret opens the content")


def _parse(raw: bytes) -> MailContent:
    try:
        plain = json.loads(raw.decode("utf-8"))
        text = plain["text"]
        html = plain.get("html")
        links = tuple(
            MailLink(str(item["url"]), item.get("expires_at")) for item in plain.get("links") or ()
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ContentUnreadableError(f"content is not {{text, html, links}}: {exc}") from exc
    if not isinstance(text, str) or (html is not None and not isinstance(html, str)):
        raise ContentUnreadableError("text/html must be strings")
    return MailContent(text, html or None, links)
