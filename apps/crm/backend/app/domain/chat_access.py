"""Доступ к переписке с клиентом отдельно от реестра лидов (B-D18-1, W18A-P3). Чистые функции.

Диалог — переписка лида с клиентом (Telegram-бот, сайт, почта): сообщения, вложения и заметки
команды. Право решает код, а не каталог целиком: каталог (`packages/contracts/platform-rbac.yaml`)
выдаёт права CRM, здесь — какое из них к какому диалогу применимо.

- **Реестр лидов** (`leads:<действие>`, раздел `crm.leads`): очередь, список, карточка, воронка — и
  любой диалог. Зона раздела `crm.leads` — все лиды.
- **Переписка** (`chats:<действие>`, раздел `chats.external`): только диалоги, где сотрудник
  **участвует** — ответственный за лида (`leads.assigned_user_id`), за клиента
  (`clients.owner_user_id`) или за сделку клиента (`deals.owner_user_id`), автор ответа клиенту в
  этом диалоге (`messages.sent_by_user_id`), — или которые **назначены его зоне**:
  `chats:invoiced` (раздел `eds.payments` на полном уровне) — диалоги клиентов, по сделке которых
  ERP выставила счёт (`deals.invoice_issued_at`, событие `erp/invoice.issued`). Зона без
  `chats:<действие>` переписку не открывает.

Чужой диалог для держателя `chats:*` — 404, как несуществующий: о существовании лида он не узнаёт.
Объектные правила действий (ответ — только ответственному после «Забрать», согласие клиента)
проверяет сервис лида после этого допуска.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

Action = Literal["read", "reply", "note", "assist"]

# Ресурсы casbin CRM: реестр лидов и переписка; действия у них одинаковые.
REGISTRY: Final = "leads"
CHATS: Final = "chats"
# Действие ресурса `chats`, которое назначает сотруднику зону «Счета и оплаты».
INVOICED_ZONE: Final = "invoiced"


class DialogAccess(StrEnum):
    """Почему сотруднику открыт диалог (поле `access` в `GET /chats`)."""

    REGISTRY = "registry"
    PARTICIPANT = "participant"
    INVOICED = "invoiced"


@dataclass(frozen=True, slots=True)
class ChatRights:
    """Права сотрудника на одно действие с диалогом (по casbin)."""

    registry: bool  # `leads:<действие>`
    chats: bool  # `chats:<действие>`
    invoiced_zone: bool  # `chats:invoiced`


@dataclass(frozen=True, slots=True)
class DialogFacts:
    """Что известно о диалоге относительно сотрудника (из БД CRM)."""

    participant: bool
    invoiced: bool


def needs_facts(rights: ChatRights) -> bool:
    """Нужно ли читать диалог из БД: реестру — нет, переписке — да, без прав — нет (403)."""
    return not rights.registry and rights.chats


def dialog_access(rights: ChatRights, facts: DialogFacts | None) -> DialogAccess | None:
    """Почему диалог открыт, или `None` — закрыт (нет прав или диалога, чужой диалог)."""
    if rights.registry:
        return DialogAccess.REGISTRY
    if not rights.chats or facts is None:
        return None
    if facts.participant:
        return DialogAccess.PARTICIPANT
    if rights.invoiced_zone and facts.invoiced:
        return DialogAccess.INVOICED
    return None
