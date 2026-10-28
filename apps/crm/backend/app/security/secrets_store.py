"""Хранилище секретов интеграций (аудит 2026-10-12 §3): Fernet-шифрование ключом `SECRETS_KEY`.

Открытый текст живёт только в памяти процесса: в БД — шифртекст и последние 4 символа,
в API и логи уходят лишь `configured`, `last4`, `updated_at`. Ключ шифрования — в `.env`,
в бэкап БД не попадает.
"""

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.integrations import IntegrationSecret

logger = structlog.get_logger(__name__)

MIN_KEY_LENGTH: Final = 32
TELEGRAM_BOT_TOKEN: Final = "telegram_bot_token"  # noqa: S105 — имя ключа, не секрет
ERP_SERVICE_TOKEN: Final = "erp_service_token"  # noqa: S105 — имя ключа, не секрет (ADR-0022)
ERP_WEBHOOK_SECRET: Final = "erp_webhook_secret"  # noqa: S105 — имя ключа, не секрет (M3-CRM-02)
# Предыдущий секрет вебхуков: принимается наравне с текущим, пока админ не снимет его (ротация без
# простоя, FIX-35).
ERP_WEBHOOK_SECRET_PREVIOUS: Final = "erp_webhook_secret_previous"  # noqa: S105 — имя ключа, не секрет
# Токен направления ERP→CRM, который CRM сама выдала при сопряжении (M3-CRM-10): ERP предъявит
# его, когда начнёт ходить в CRM (общие настройки, M3-CRM-11). Сегодня CRM его только хранит.
ERP_INBOUND_TOKEN: Final = "erp_inbound_token"  # noqa: S105 — имя ключа, не секрет (M3-CRM-10)
# «Ожидающая» тройка «Обновить ключи» (M3-CRM-10): хранится, пока ERP не подтвердила её однозначно,
# чтобы после обрыва связи повтор отправил ТУ ЖЕ тройку (ERP идемпотентна по ней, CONTRACTS §2).
ERP_PENDING_SERVICE_TOKEN: Final = "erp_pending_service_token"  # noqa: S105 — имя ключа, не секрет
ERP_PENDING_INBOUND_TOKEN: Final = "erp_pending_inbound_token"  # noqa: S105 — имя ключа, не секрет
ERP_PENDING_WEBHOOK_SECRET: Final = "erp_pending_webhook_secret"  # noqa: S105 — имя ключа, не секрет
SMTP_USERNAME: Final = "smtp_username"
SMTP_PASSWORD: Final = "smtp_password"  # noqa: S105 — имя ключа, не секрет (M3-CRM-08)
# JSON-ключ сервисного аккаунта Google внешней копии бэкапов (OPS-GDRIVE-2).
OFFSITE_GDRIVE_KEY: Final = "offsite_gdrive_key"


class SecretsKeyError(RuntimeError):
    """`SECRETS_KEY` не задан или не подходит к шифртексту."""


@dataclass(frozen=True, slots=True)
class SecretStatus:
    last4: str
    updated_at: datetime


def last4(value: str) -> str:
    return value[-4:] if len(value) >= 8 else "****"


class SecretCipher:
    """Ключ Fernet выводится из `SECRETS_KEY` через SHA-256: подходит `openssl rand -hex 32`."""

    def __init__(self, key: str) -> None:
        if not key:
            raise SecretsKeyError("SECRETS_KEY is not set")
        if len(key) < MIN_KEY_LENGTH:
            raise SecretsKeyError(f"SECRETS_KEY must be at least {MIN_KEY_LENGTH} characters")
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
        self._fernet = Fernet(derived)

    @classmethod
    def optional(cls, key: str) -> "SecretCipher | None":
        try:
            return cls(key)
        except SecretsKeyError:
            if key:
                logger.error("secrets_key_invalid")
            return None

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise SecretsKeyError("ciphertext does not match SECRETS_KEY") from exc


class SecretsStore:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], cipher: SecretCipher | None
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher

    @property
    def enabled(self) -> bool:
        return self._cipher is not None

    async def get(self, key: str) -> str | None:
        """Открытое значение или None (нет строки, нет ключа или ключ сменился)."""
        if self._cipher is None:
            return None
        async with self._sessions() as session:
            row = await session.get(IntegrationSecret, key)
        if row is None:
            return None
        try:
            return self._cipher.decrypt(row.ciphertext)
        except SecretsKeyError:
            logger.error("secret_undecryptable", key=key)
            return None

    async def status(self, key: str) -> SecretStatus | None:
        async with self._sessions() as session:
            row = (
                await session.execute(select(IntegrationSecret).where(IntegrationSecret.key == key))
            ).scalar_one_or_none()
        return None if row is None else SecretStatus(row.last4, row.updated_at)

    async def delete(self, session: AsyncSession, key: str) -> None:
        """Снять секрет в транзакции вызывающего (вместе с аудитом); нет строки — ничего."""
        await session.execute(sa_delete(IntegrationSecret).where(IntegrationSecret.key == key))

    async def put(self, session: AsyncSession, key: str, value: str, user_id: int | None) -> None:
        """Записать в транзакции вызывающего (вместе с аудитом)."""
        if self._cipher is None:
            raise SecretsKeyError("SECRETS_KEY is not set")
        values = {
            "key": key,
            "ciphertext": self._cipher.encrypt(value),
            "last4": last4(value),
            "updated_by": user_id,
        }
        stmt = insert(IntegrationSecret).values(**values)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[IntegrationSecret.key],
                set_={
                    "ciphertext": stmt.excluded.ciphertext,
                    "last4": stmt.excluded.last4,
                    "updated_by": stmt.excluded.updated_by,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )
