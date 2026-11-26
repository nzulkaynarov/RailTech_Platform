"""Беседа известного контакта компании (КОНТР-1а): сообщение человека, который уже контакт
контрагента, — не новый лид, а переписка компании.

Лид остаётся записью беседы (история на месте), но помечается ключом `known_contact` в
`qualification` и ведётся ответственным за компанию. Бот отвечает как прежде (`owner_mode`
не меняется), поэтому «непрочитанное» и личное уведомление для такого лида считаются иначе,
чем для лида, которого ведёт человек.
"""

from collections.abc import Mapping
from typing import Any, Final

MARK_KEY: Final = "known_contact"


def is_company_conversation(
    owner_mode: str,
    assigned_user_id: int | None,
    client_id: int | None,
    qualification: Mapping[str, Any] | None,
) -> bool:
    """Лид — беседа известного контакта, которую ведёт ответственный за компанию при работающем
    боте."""
    return (
        owner_mode == "bot"
        and assigned_user_id is not None
        and client_id is not None
        and MARK_KEY in (qualification or {})
    )
