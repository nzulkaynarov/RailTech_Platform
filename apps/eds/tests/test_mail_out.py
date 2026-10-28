"""Письмо EDS — запрос почтовому сервису CRM по шине (W18A-P1): одно событие в транзакции, тело шифртекстом пары."""

import hashlib
import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.container import Container
from app.services.mail_out import LinkedAttachment, MailRequestError, content_key, request_mail
from tests.domain import outbox

pytestmark = pytest.mark.pg

PAIR = "test-pair-secret-eds-crm-".ljust(40, "x")
# Тест-вектор формата `fernet-pair-v1` (тот же — в тестах CRM и ERP): секрет → ключ → токен.
VECTOR_SECRET = "test-pair-secret-erp-crm"
VECTOR_KEY = b"X9hy9oZT8E1lJ-2hJu430cg_YyaOednsYENWMNC0eSs="
PDF = b"%PDF-1.7 letter"


def attachment() -> LinkedAttachment:
    return LinkedAttachment(
        filename="ИСХ-2026-0031.pdf",
        content_type="application/pdf",
        size=len(PDF),
        sha256=hashlib.sha256(PDF).hexdigest(),
        url="http://rustfs:9000/eds-private/files/1/v1?X-Amz-Signature=00",
        expires_at="2026-10-29T09:00:00Z",
    )


def test_content_key_is_the_shared_format() -> None:
    assert content_key(VECTOR_SECRET) == VECTOR_KEY


async def test_letter_goes_as_one_event_with_sealed_body(container: Container, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    async with container.session_factory() as session, session.begin():
        await request_mail(
            container.bus,
            session,
            request_key="eds:letter:77",
            purpose="outgoing_letter",
            to=["office@example.org"],
            subject="Письмо ИСХ-2026-0031",
            text="Текст письма",
            html="<p>Текст письма</p>",
            ref=("letter", "77"),
            attachments=[attachment()],
        )
    (event,) = await outbox(container, "mail.requested")
    data = event["data"]
    assert (data["request_key"], data["purpose"], data["to"]) == (
        "eds:letter:77",
        "outgoing_letter",
        ["office@example.org"],
    )
    assert data["attachments"][0]["filename"] == "ИСХ-2026-0031.pdf"
    assert "Текст письма" not in json.dumps(data, ensure_ascii=False)
    assert "X-Amz-Signature" not in json.dumps(data)
    plain = json.loads(Fernet(content_key(PAIR)).decrypt(data["content"]["ciphertext"].encode()))
    assert plain == {
        "text": "Текст письма",
        "html": "<p>Текст письма</p>",
        "links": [{"url": attachment().url, "expires_at": "2026-10-29T09:00:00Z"}],
    }


async def test_rollback_leaves_no_request_and_missing_pair_secret_is_an_error(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)

    async def change_then_fail() -> None:
        async with container.session_factory() as session, session.begin():
            await request_mail(
                container.bus,
                session,
                request_key="eds:letter:1",
                purpose="outgoing_letter",
                to=["a@example.org"],
                subject="s",
                text="t",
            )
            raise RuntimeError("откат изменения")

    with pytest.raises(RuntimeError):
        await change_then_fail()
    async with container.session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM rt_bus_outbox"))).scalar_one() == 0

    monkeypatch.delenv("RT_BUS_SECRET_EDS_CRM")

    async def without_secret() -> None:
        async with container.session_factory() as session, session.begin():
            await request_mail(
                container.bus,
                session,
                request_key="eds:letter:2",
                purpose="outgoing_letter",
                to=["a@example.org"],
                subject="s",
                text="t",
            )

    with pytest.raises(MailRequestError):
        await without_secret()


async def test_memory_storage_presigns_a_link() -> None:
    from app.services.storage import MemoryStorage

    assert (await MemoryStorage().presign("files/1/v1", 3600)).startswith("memory://eds-private/files/1/v1")
