"""«Почта · Отправленные» (план 2.8, MAIL-1): поиск по журналу писем; свои — сотруднику,
все — администратору; текст — по запросу с записью в аудит."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.models.email import EmailLog
from app.security.secrets_store import SecretCipher
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration

URL = "/api/v1/mail/sent"
SECRETS_KEY = "k" * 64


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    with TestClient(create_app(settings)) as test_client:
        yield test_client


async def test_employee_sees_own_admin_sees_all_body_is_audited(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    manager, password = await make_user(sessions, "manager@railtech.uz", ["manager"])
    admin, admin_password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    cipher = SecretCipher(SECRETS_KEY)
    async with sessions() as session, session.begin():
        for n, (who, ref) in enumerate(
            [(manager.id, "ИСХ-014/26"), (manager.id, None), (admin.id, None)]
        ):
            session.add(
                EmailLog(
                    to_email=f"client{n}@example.uz",
                    subject=f"Письмо {n}" if ref is None else "Ответ на требование",
                    template="eds_letter",
                    lang="ru",
                    status="sent",
                    source="eds",
                    requested_by=who,
                    ref_kind="eds_document" if ref else None,
                    ref_id=ref,
                    body_ciphertext=cipher.encrypt(f"Текст {n}"),
                    attachments=[{"filename": "letter.pdf", "content_type": "application/pdf"}],
                )
            )
    mine = login(client, manager.email, password)
    boss = login(client, admin.email, admin_password)

    own = client.get(URL, headers=mine).json()
    assert {i["to_email"] for i in own["items"]} == {"client0@example.uz", "client1@example.uz"}
    assert own["items"][0]["requested_by_name"] == "manager"
    every = client.get(URL, headers=boss).json()["items"]
    assert len(every) == 3
    found = client.get(URL, params={"q": "требован"}, headers=mine).json()["items"]
    assert [i["ref_id"] for i in found] == ["ИСХ-014/26"]
    by_ref = client.get(
        URL, params={"ref_kind": "eds_document", "ref_id": "ИСХ-014/26"}, headers=boss
    ).json()
    assert [i["to_email"] for i in by_ref["items"]] == ["client0@example.uz"]
    first = client.get(URL, params={"limit": 1}, headers=boss).json()
    second = client.get(
        URL, params={"limit": 1, "cursor": first["next_cursor"]}, headers=boss
    ).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert client.get(URL, params={"cursor": "мусор"}, headers=boss).status_code == 422

    admin_row = next(i for i in every if i["requested_by"] == admin.id)
    assert client.get(f"{URL}/{admin_row['id']}", headers=mine).status_code == 404, (
        "чужое письмо сотруднику не видно"
    )
    own_row = own["items"][0]
    body = client.get(f"{URL}/{own_row['id']}", headers=mine).json()
    assert body["text"].startswith("Текст")
    assert body["attachments"] == ["letter.pdf"]
    async with sessions() as session:
        audited = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "mail.body_view"))
        ).all()
    assert [a.entity_id for a in audited] == [str(own_row["id"])]
