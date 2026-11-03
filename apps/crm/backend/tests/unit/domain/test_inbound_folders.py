"""Папки общего ящика и загрузка истории (W18A-P2-2): правила без I/O."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.inbound_folders import (
    HISTORY_DAYS,
    HISTORY_LIMIT,
    TASK_WINDOW_DAYS,
    FolderSetting,
    ServerFolder,
    decode_folder,
    is_history,
    parse_list,
    pick_history,
    primary_folder,
    resolve_folders,
    suggest_spam,
)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def test_constants_owner_decision() -> None:
    """Владелец 2026-11-03: задачи — за 3 дня; периоды 7/14/30/90; предел загрузки — 2000."""
    assert TASK_WINDOW_DAYS == 3
    assert HISTORY_DAYS == (7, 14, 30, 90)
    assert HISTORY_LIMIT == 2000


@pytest.mark.parametrize(
    ("sent_at", "expected"),
    [
        (NOW - timedelta(hours=1), False),
        (NOW - timedelta(days=TASK_WINDOW_DAYS) + timedelta(minutes=1), False),
        (NOW - timedelta(days=TASK_WINDOW_DAYS, minutes=1), True),
        (NOW - timedelta(days=60), True),
        (NOW + timedelta(days=1), False),  # дата в будущем (часы отправителя) — не история
        (None, True),  # без даты: свежие уже забрал обычный опрос
    ],
)
def test_is_history_by_task_window(sent_at: datetime | None, expected: bool) -> None:
    assert is_history(sent_at, NOW) is expected


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("INBOX", "INBOX"),
        ("&BCEEPwQwBDw-", "Спам"),
        ("&BBoEPgRABDcEOAQ9BDA-", "Корзина"),
        ("Tom &- Jerry", "Tom & Jerry"),
        ("[Gmail]/Spam", "[Gmail]/Spam"),
        ("Broken &zzz", "Broken &zzz"),
    ],
)
def test_decode_modified_utf7(raw: str, label: str) -> None:
    assert decode_folder(raw) == label


def test_parse_list_flags_quotes_and_literals() -> None:
    lines: list[bytes | tuple[bytes, bytes]] = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\Junk) "|" "Spam"',
        b'(\\Noselect \\HasChildren) "/" "[Gmail]"',
        b'(\\HasNoChildren) "/" &BCEEPwQwBDw-',
        (b'(\\HasNoChildren) "/" {11}', b"Quoted Name"),
        b"garbage",
    ]
    folders = parse_list(lines)
    assert [f.name for f in folders] == ["INBOX", "Spam", "[Gmail]", "&BCEEPwQwBDw-", "Quoted Name"]
    assert [f.junk for f in folders] == [False, True, False, False, False]
    assert folders[2].selectable is False
    assert folders[3].label == "Спам"


@pytest.mark.parametrize(
    ("folders", "expected"),
    [
        # Флаг \Junk решает, даже если имя непривычное.
        (
            [ServerFolder("INBOX", "INBOX", False, True), ServerFolder("Bulk", "Bulk", True, True)],
            "Bulk",
        ),
        # Флага нет — одно привычное имя.
        (
            [
                ServerFolder("INBOX", "INBOX", False, True),
                ServerFolder("&BCEEPwQwBDw-", "Спам", False, True),
            ],
            "&BCEEPwQwBDw-",
        ),
        # Два кандидата без флага — выбирает человек.
        (
            [ServerFolder("Spam", "Spam", False, True), ServerFolder("Junk", "Junk", False, True)],
            None,
        ),
        ([ServerFolder("INBOX", "INBOX", False, True)], None),
    ],
)
def test_suggest_spam(folders: list[ServerFolder], expected: str | None) -> None:
    assert suggest_spam(folders) == expected


def test_resolve_folders_defaults_and_dedup() -> None:
    assert resolve_folders([], "INBOX") == (FolderSetting("INBOX"),)
    assert resolve_folders([], " ") == (FolderSetting("INBOX"),)
    got = resolve_folders(
        [FolderSetting("INBOX"), FolderSetting(" Spam ", True), FolderSetting("INBOX", True)], "x"
    )
    assert got == (FolderSetting("INBOX"), FolderSetting("Spam", True))
    assert primary_folder(got) == "INBOX"
    assert primary_folder([FolderSetting("Spam", True)]) == "INBOX"


def test_pick_history_regular_first_newest_first_with_limit() -> None:
    inbox, spam = FolderSetting("INBOX"), FolderSetting("Spam", True)
    chosen, limited = pick_history([(spam, [1, 2, 3]), (inbox, [10, 11, 12, 11])], limit=4)
    assert chosen == [(inbox, [12, 11, 10]), (spam, [3])]
    assert limited is True
    chosen, limited = pick_history([(inbox, [5])], limit=4)
    assert (chosen, limited) == ([(inbox, [5])], False)
    assert pick_history([(inbox, [])]) == ([], False)
