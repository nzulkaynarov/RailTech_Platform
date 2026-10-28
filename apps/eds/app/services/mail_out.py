"""Письма EDS — через почтовый сервис CRM (W18A-P1, B-INB-6): один отправитель на ансамбль.

EDS SMTP не знает и писем сам не шлёт. Письмо (например, письмо на бланке адресату — задача P4 волны 18a) — событие
`uz.railtech.eds.mail.requested.v1` (`packages/contracts/events/eds/mail.requested.v1.json`) в транзакции изменения:
EDS рендерит тему, текст и HTML своим шаблоном, CRM доставляет через SMTP карточки «Почта», ведёт журнал доставки и
повторы. Повтор с тем же `request_key` второго письма не даёт.

- Текст, HTML и ссылки на вложения — шифртекстом ключа пары «eds → crm» (`fernet-pair-v1`: Fernet, ключ =
  urlsafe_b64(HMAC-SHA256(секрет пары, "rt-mail/v1/content"))), секрет — `RT_BUS_SECRET_EDS_CRM`.
- Вложение — по ссылке на объект своего хранилища (`eds-private`, ключи S3 у EDS свои, S0-9): подписанная ссылка на
  чтение одного объекта со сроком (`ObjectStorage.presign`); в открытой части события — имя, тип, размер, sha256.
- Итог доставки (`uz.railtech.crm.mail.sent|failed.v1`) EDS пока не слушает: `notify=True` и подписку `eds` в
  `bus/subscriptions.yaml` добавит задача, которой итог нужен (P4, BACKLOG B-W18AP1-1).
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from cryptography.fernet import Fernet
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.events import publish

ALG: Final = "fernet-pair-v1"
_LABEL: Final = b"rt-mail/v1/content"
REQUESTER: Final = "eds"
MAIL_SERVICE: Final = "crm"


class MailRequestError(Exception):
    """Запрос письма не собрать (нет секрета пары «eds → crm»)."""


@dataclass(frozen=True, slots=True)
class LinkedAttachment:
    """Вложение по ссылке: объект хранилища EDS и подписанная ссылка на чтение со сроком."""

    filename: str
    content_type: str
    size: int
    sha256: str
    url: str
    expires_at: str


def content_key(pair_secret: str) -> bytes:
    return base64.urlsafe_b64encode(hmac.new(pair_secret.encode("utf-8"), _LABEL, hashlib.sha256).digest())


def seal(pair_secret: str, *, text: str, html: str | None, links: Sequence[dict[str, str]]) -> str:
    raw = json.dumps(
        {"text": text, "html": html or None, "links": list(links)}, ensure_ascii=False, separators=(",", ":")
    )
    return Fernet(content_key(pair_secret)).encrypt(raw.encode("utf-8")).decode("ascii")


async def request_mail(
    bus: AsyncBus,
    session: AsyncSession,
    *,
    request_key: str,
    purpose: str,
    to: Sequence[str],
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
    language: str | None = None,
    ref: tuple[str, str] | None = None,
    notify: bool = False,
    attachments: Sequence[LinkedAttachment] = (),
) -> dict[str, Any]:
    """Опубликовать запрос письма в транзакции `session`; возвращает `data` события."""
    secrets = bus.config.secrets(REQUESTER, MAIL_SERVICE)
    if not secrets:
        raise MailRequestError("нет секрета пары eds → crm (RT_BUS_SECRET_EDS_CRM)")
    links = [{"url": a.url, "expires_at": a.expires_at} for a in attachments]
    data: dict[str, Any] = {
        "request_key": request_key,
        "purpose": purpose,
        "to": list(to),
        "subject": " ".join(subject.split())[:255],
        "notify": notify,
        "content": {"alg": ALG, "ciphertext": seal(secrets[0], text=text, html=html, links=links)},
    }
    if reply_to:
        data["reply_to"] = reply_to
    if language:
        data["language"] = language
    if ref is not None:
        data["ref"] = {"kind": ref[0], "id": ref[1]}
    if attachments:
        data["attachments"] = [
            {"filename": a.filename, "content_type": a.content_type, "size": a.size, "sha256": a.sha256}
            for a in attachments
        ]
    await publish(bus, session, "mail.requested", data, subject=f"mail/{request_key}")
    return data
