"""Параметр `/start` бота (deep-link): метка источника, заявка кабинета, подписанная ссылка (D1-9).

Что приходит после `/start`:

* `web` — клиент нажал «Написать в Telegram» на сайте; метка источника нового лида, привязывать
  нечего;
* `deal_<id>` — «Написать менеджеру» из кабинета (`id` — заявка ERP). Ссылку собирает кабинет без
  подписи, поэтому привязка проверяется по аккаунту: заявка должна принадлежать клиенту, к
  которому уже привязан и которого проверил менеджер этот Telegram;
* `lead_<id>_<срок>_<подпись>` — ссылка из письма-подтверждения, выданная самой системой (id и
  срок в base36, подпись HMAC на отдельном ключе `link_key`), живёт `LEAD_LINK_TTL`. Склеивает
  чат с запросом с сайта. Одноразовость — состоянием: если у запроса уже есть Telegram-аккаунт,
  он обезличен, а чат принадлежит клиенту (`client_id`), ссылка не срабатывает.

Всё остальное — `unknown`: бот просто здоровается. Чистые функции без I/O.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

LEAD_LINK_TTL: Final = timedelta(days=14)
_SIG_LEN: Final = 16
_DEAL: Final = re.compile(r"^deal_(\d{1,12})$")
_LEAD: Final = re.compile(r"^lead_([0-9a-z]{1,12})_([0-9a-z]{1,12})_([0-9a-f]{16})$")
_INFO: Final = b"rt-crm/start-link/v1"

Kind = Literal["none", "web", "deal", "lead", "unknown"]


@dataclass(frozen=True, slots=True)
class StartLink:
    kind: Kind
    #: `deal` — id заявки ERP; `lead` — id запроса (после проверки подписи вызывающим через
    #: `verify_lead_link`).
    deal_id: int | None = None
    raw: str | None = None


def parse_start_payload(raw: str | None) -> StartLink:
    """Разбор параметра `/start`; мусор и чужие форматы — `unknown`, без исключений."""
    text = (raw or "").strip()
    if not text:
        return StartLink("none")
    if text == "web":
        return StartLink("web")
    deal = _DEAL.match(text)
    if deal:
        return StartLink("deal", deal_id=int(deal.group(1)))
    if _LEAD.match(text):
        return StartLink("lead", raw=text)
    return StartLink("unknown")


def link_key(secret: bytes) -> bytes:
    """Ключ подписи ссылок: HKDF-SHA256 (RFC 5869) от секрета приложения с контекстом `start-link`.

    Свой ключ, а не сам `JWT_SECRET`: подпись ссылки бота не должна совпадать с подписями токенов
    других назначений, даже если их формат когда-нибудь совпадёт."""
    prk = hmac.new(b"\x00" * hashlib.sha256().digest_size, secret, hashlib.sha256).digest()
    return hmac.new(prk, _INFO + b"\x01", hashlib.sha256).digest()


def _sign(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()[:_SIG_LEN]


def _b36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while value:
        value, rest = divmod(value, 36)
        out = digits[rest] + out
    return out or "0"


def issue_lead_link(key: bytes, lead_id: int, now: datetime) -> str:
    """Параметр `start` для письма: `lead_<id>_<срок>_<подпись>` (до 40 символов, лимит
    Telegram — 64)."""
    expires = _b36(int((now + LEAD_LINK_TTL).timestamp()))
    body = f"{_b36(lead_id)}_{expires}"
    return f"lead_{body}_{_sign(key, body)}"


def verify_lead_link(key: bytes, raw: str, now: datetime) -> int | None:
    """id запроса, если подпись верна и срок не вышел; иначе `None`."""
    match = _LEAD.match(raw or "")
    if match is None:
        return None
    lead_b36, exp_b36, signature = match.groups()
    if not hmac.compare_digest(signature, _sign(key, f"{lead_b36}_{exp_b36}")):
        return None
    if datetime.fromtimestamp(int(exp_b36, 36), tz=UTC) < now:
        return None
    return int(lead_b36, 36)
