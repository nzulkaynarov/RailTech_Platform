"""Правило доступа к переписке отдельно от реестра лидов (B-D18-1): таблица случаев."""

import pytest

from app.domain.chat_access import (
    ChatRights,
    DialogAccess,
    DialogFacts,
    dialog_access,
    needs_facts,
)

REGISTRY = ChatRights(registry=True, chats=False, invoiced_zone=False)
CHATS = ChatRights(registry=False, chats=True, invoiced_zone=False)
ACCOUNTANT = ChatRights(registry=False, chats=True, invoiced_zone=True)
ZONE_ONLY = ChatRights(registry=False, chats=False, invoiced_zone=True)
NOTHING = ChatRights(registry=False, chats=False, invoiced_zone=False)

FOREIGN = DialogFacts(participant=False, invoiced=False)
MINE = DialogFacts(participant=True, invoiced=False)
INVOICED = DialogFacts(participant=False, invoiced=True)
MINE_INVOICED = DialogFacts(participant=True, invoiced=True)


@pytest.mark.parametrize(
    ("rights", "facts", "expected"),
    [
        # Реестр лидов (`crm.leads`): любой диалог, факты не нужны.
        (REGISTRY, None, DialogAccess.REGISTRY),
        (REGISTRY, FOREIGN, DialogAccess.REGISTRY),
        # Переписка без зоны (менеджер без реестра): только свои.
        (CHATS, MINE, DialogAccess.PARTICIPANT),
        (CHATS, FOREIGN, None),
        (CHATS, INVOICED, None),  # счёт выставлен, но зоны «Счета и оплаты» нет
        (CHATS, None, None),  # диалога нет или обезличен
        # Бухгалтер: свои и сделки со счётом.
        (ACCOUNTANT, INVOICED, DialogAccess.INVOICED),
        (ACCOUNTANT, MINE_INVOICED, DialogAccess.PARTICIPANT),
        (ACCOUNTANT, MINE, DialogAccess.PARTICIPANT),
        (ACCOUNTANT, FOREIGN, None),
        # Зона без права на переписку ничего не открывает.
        (ZONE_ONLY, INVOICED, None),
        (NOTHING, MINE_INVOICED, None),
    ],
)
def test_dialog_access(
    rights: ChatRights, facts: DialogFacts | None, expected: DialogAccess | None
) -> None:
    assert dialog_access(rights, facts) is expected


@pytest.mark.parametrize(
    ("rights", "expected"),
    [(REGISTRY, False), (CHATS, True), (ACCOUNTANT, True), (ZONE_ONLY, False), (NOTHING, False)],
)
def test_facts_are_read_only_for_chat_holders(rights: ChatRights, expected: bool) -> None:
    assert needs_facts(rights) is expected
