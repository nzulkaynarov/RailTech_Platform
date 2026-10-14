"""Антиспам формы «Запрос» с сайта (ARCHITECTURE §17, M3-CRM-05). Чистые функции без I/O.

Три детерминированных барьера: honeypot-поле (человек его не видит и не заполняет), подписанный
токен формы с временем выдачи (минимальное время заполнения и срок жизни) и скользящее окно
запросов по IP. Пороги — `settings.web_form` (скилл `settings-key`), не константы в коде.
"""

import hashlib
import hmac
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

_SIG_LEN: Final = 32
_SEP: Final = "."


class TokenVerdict(StrEnum):
    OK = "ok"
    INVALID = "form_token_invalid"
    TOO_FAST = "form_too_fast"
    EXPIRED = "form_token_expired"


def _sign(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()[:_SIG_LEN]


def issue_form_token(key: bytes, now: datetime) -> str:
    """`<unix-секунды>.<HMAC>` — выдаётся вместе с формой; хранить на сервере ничего не нужно."""
    issued = str(int(now.timestamp()))
    return f"{issued}{_SEP}{_sign(key, issued)}"


def check_form_token(
    key: bytes, token: str | None, now: datetime, *, min_fill_s: int, ttl_s: int
) -> TokenVerdict:
    """Подпись верна, форму заполняли не меньше `min_fill_s` и не дольше `ttl_s` секунд."""
    if not token or _SEP not in token:
        return TokenVerdict.INVALID
    issued_text, _, signature = token.partition(_SEP)
    if not issued_text.isdigit() or not hmac.compare_digest(signature, _sign(key, issued_text)):
        return TokenVerdict.INVALID
    issued = datetime.fromtimestamp(int(issued_text), tz=UTC)
    elapsed = (now - issued).total_seconds()
    if elapsed < min_fill_s:
        return TokenVerdict.TOO_FAST
    if elapsed > ttl_s:
        return TokenVerdict.EXPIRED
    return TokenVerdict.OK


def is_honeypot_filled(value: str | None) -> bool:
    """Скрытое поле `website` заполнено — это бот; запрос молча не создаётся."""
    return bool(value and value.strip())


@dataclass
class SlidingWindowLimiter:
    """Не больше `limit` обращений за `window_s` секунд на ключ (IP). В памяти процесса.

    Для одного процесса api этого достаточно (как у `RateLimitMiddleware` бота); при
    горизонтальном масштабировании окно переносится в Postgres (открытый вопрос Q-13).
    """

    limit: int
    window_s: int
    _hits: dict[str, deque[float]] = field(default_factory=dict)

    def allow(self, key: str, now: datetime, *, limit: int | None = None) -> bool:
        """`limit` на вызов — порог из настроек, который админ меняет без перезапуска."""
        moment = now.timestamp()
        hits = self._hits.setdefault(key, deque())
        while hits and moment - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= (self.limit if limit is None else limit):
            return False
        hits.append(moment)
        return True

    def forget_stale(self, now: datetime) -> None:
        """Чистка ключей, у которых окно давно пустое (чтобы словарь не рос бесконечно)."""
        moment = now.timestamp()
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or moment - hits[-1] >= self.window_s
        ]
        for key in stale:
            del self._hits[key]
