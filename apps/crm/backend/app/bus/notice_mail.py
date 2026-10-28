"""Письмо клиенту — запасной канал сообщений по событиям ERP (D1-9, SPEC-v3 §8): бот, иначе письмо.

Помощники `ErpEventNotices` (`app/bus/notices.py`): кому писать, если у клиента нет Telegram,
отправка через
`MailService` и запись итога в `client_notices` для карточки клиента. Адрес — основной контакт
клиента, иначе
любой контакт с адресом, иначе почта лида клиента.
"""

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ConflictError
from app.models.clients import ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.notices import ClientNotice
from app.services.mail import MailService
from app.services.mail_templates import RenderedEmail

logger = structlog.get_logger(__name__)


async def client_chats(session: AsyncSession, client_id: int, *, with_leads: bool) -> list[int]:
    """Telegram клиента: аккаунты, привязанные к клиенту; `with_leads` — ещё и аккаунты его лидов
    (так передача в ERP берёт `telegram_user_id`), не заблокировавшие бота."""
    condition = TelegramIdentity.client_id == client_id
    if with_leads:
        lead_ids = select(Lead.id).where(Lead.client_id == client_id)
        condition = condition | TelegramIdentity.lead_id.in_(lead_ids)
    rows = await session.scalars(
        select(TelegramIdentity.tg_user_id)
        .where(condition, TelegramIdentity.is_blocked.is_(False))
        .order_by(TelegramIdentity.id)
    )
    return list(dict.fromkeys(rows.all()))


async def client_email(session: AsyncSession, client_id: int) -> str | None:
    """Куда писать клиенту без Telegram: основной контакт, любой контакт с адресом, лид клиента."""
    contact = await session.scalar(
        select(ClientContact.email)
        .where(ClientContact.client_id == client_id, ClientContact.email.is_not(None))
        .order_by(ClientContact.is_primary.desc(), ClientContact.id)
        .limit(1)
    )
    if contact and contact.strip():
        return contact.strip()
    lead = await session.scalar(
        select(Lead.email)
        .where(Lead.client_id == client_id, Lead.email.is_not(None), Lead.erased_at.is_(None))
        .order_by(Lead.id.desc())
        .limit(1)
    )
    return lead.strip() if lead and lead.strip() else None


def rendered(item: dict[str, Any]) -> RenderedEmail:
    mail = item["email"]
    return RenderedEmail(mail["subject"], mail["body"], mail.get("lang", "ru"))


async def send(mail: MailService | None, template: str, to: str, content: RenderedEmail) -> str:
    """`queued` — письмо в очереди; `skipped` — слать нечем (почта не настроена, постоянно);
    `error` — сбой, который стоит повторить."""
    if mail is None:
        return "skipped"
    try:
        await mail.send_rendered(template, to, content)
    except ConflictError:
        logger.warning("erp_event_mail_skipped", template=template)
        return "skipped"
    except Exception:
        logger.exception("erp_event_mail_failed", template=template)
        return "error"
    return "queued"


async def record(
    session: AsyncSession,
    *,
    kind: str,
    client_id: int,
    channel: str,
    status: str,
    error: str | None,
    dedupe_key: str,
) -> None:
    """Итог для карточки клиента; повторная доставка того же события строку не дублирует."""
    exists = await session.scalar(
        select(ClientNotice.id).where(ClientNotice.dedupe_key == dedupe_key)
    )
    if exists is None:
        session.add(
            ClientNotice(
                kind=kind,
                client_id=client_id,
                channel=channel,
                status=status,
                error=error,
                dedupe_key=dedupe_key,
            )
        )
