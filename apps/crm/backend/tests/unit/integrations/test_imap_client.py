"""Клиент IMAP против фейкового сервера (W18A-P2): только чтение, UID и UIDVALIDITY, ошибки."""

from email.message import EmailMessage

import pytest

from app.integrations.imap import ImapConnection, ImaplibClient, ImapProbeError
from tests.fake_imap import PASSWORD, USERNAME, FakeImapServer, PlainClient


def _raw(n: int) -> bytes:
    msg = EmailMessage()
    msg["From"] = "sender@example.test"
    msg["Subject"] = f"Письмо {n}"
    msg["Message-ID"] = f"<m{n}@example.test>"
    msg.set_content(f"Текст {n}")
    return msg.as_bytes().replace(b"\n", b"\r\n")


def _conn(port: int, *, password: str = PASSWORD, mailbox: str = "INBOX") -> ImapConnection:
    return ImapConnection("127.0.0.1", port, "ssl", mailbox, USERNAME, password)


async def test_check_counts_messages_read_only() -> None:
    with FakeImapServer() as server:
        server.box.add(5, _raw(5))
        result = await PlainClient().check(_conn(server.port))
    assert result.messages == 1
    assert not server.box.selected_readwrite


async def test_fetch_first_then_resume_after_last_uid() -> None:
    with FakeImapServer() as server:
        server.box.add(10, _raw(10))
        server.box.add(11, _raw(11))
        client = PlainClient()
        first = await client.fetch(_conn(server.port), None, None)
        assert first.uidvalidity == 1001
        assert [m.uid for m in first.messages] == [10, 11]
        assert b"Message-ID: <m10@example.test>" in first.messages[0].raw
        # Новых нет: «UID 12:*» по RFC отдаёт последнее письмо — клиент его отбрасывает.
        again = await client.fetch(_conn(server.port), 1001, 11)
        assert again.messages == ()
        server.box.add(12, _raw(12))
        third = await client.fetch(_conn(server.port), 1001, 11)
        assert [m.uid for m in third.messages] == [12]
    assert server.box.writes == []
    assert not server.box.selected_readwrite


async def test_uidvalidity_change_rescans() -> None:
    with FakeImapServer() as server:
        server.box.add(3, _raw(3))
        batch = await PlainClient().fetch(_conn(server.port), 999, 50)
    assert [m.uid for m in batch.messages] == [3]


async def test_wrong_password_is_auth_failed() -> None:
    with FakeImapServer() as server, pytest.raises(ImapProbeError) as caught:
        await PlainClient().check(_conn(server.port, password="wrong"))
    assert caught.value.kind == "auth_failed"


async def test_missing_mailbox() -> None:
    with FakeImapServer() as server, pytest.raises(ImapProbeError) as caught:
        await PlainClient().check(_conn(server.port, mailbox="Archive"))
    assert caught.value.kind == "mailbox_missing"


async def test_unreachable_host() -> None:
    with pytest.raises(ImapProbeError) as caught:
        await PlainClient().check(_conn(1))
    assert caught.value.kind == "unavailable"


async def test_invalid_host() -> None:
    conn = ImapConnection("bad host", 993, "ssl", "INBOX", USERNAME, PASSWORD)
    with pytest.raises(ImapProbeError) as caught:
        await ImaplibClient().check(conn)
    assert caught.value.kind == "invalid_host"


# --- папки и загрузка истории (W18A-P2-2) -----------------------------------------------------


async def test_folders_lists_names_and_junk_flag() -> None:
    with FakeImapServer() as server:
        server.folder("Spam", "\\HasNoChildren \\Junk")
        server.folder("&BCEEPwQwBDw-")
        folders = await PlainClient().folders(_conn(server.port))
    assert [(f.name, f.label, f.junk) for f in folders] == [
        ("INBOX", "INBOX", False),
        ("Spam", "Spam", True),
        ("&BCEEPwQwBDw-", "Спам", False),
    ]
    assert server.box.writes == []


async def test_search_since_and_fetch_uids_in_other_folder() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    with FakeImapServer() as server:
        spam = server.folder("Spam", "\\Junk", uidvalidity=77)
        spam.add(1, _raw(1), now - timedelta(days=40))
        spam.add(2, _raw(2), now - timedelta(days=10))
        spam.add(3, _raw(3), now)
        client = PlainClient()
        uidvalidity, uids = await client.search_since(_conn(server.port, mailbox="Spam"), 14)
        assert (uidvalidity, uids) == (77, [2, 3])
        got = await client.fetch_uids(_conn(server.port, mailbox="Spam"), [3, 2, 99])
    assert [m.uid for m in got] == [3, 2], "UID 99 нет на сервере — пропущен"
    assert b"<m3@example.test>" in got[0].raw
    assert spam.writes == []
    assert not server.box.selected_readwrite
