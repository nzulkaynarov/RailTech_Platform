"""Помощники integration-тестов CRM: пользователи, вход, лид с эскалацией."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.qualification import Escalation
from app.repositories import leads as repo
from app.security.audit import Actor
from app.services.users import UserService

PASSWORD = "Str0ng-password-42"


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> Any:
        self.sent.append((chat_id, text))
        return type("Sent", (), {"message_id": len(self.sent)})()


@dataclass
class Account:
    id: int
    email: str


async def make_user(
    sessions: async_sessionmaker[AsyncSession], email: str, roles: list[str], *, ready: bool = True
) -> tuple[Account, str]:
    """Пользователь; `ready` — пароль уже сменён (иначе — временный пароль)."""
    service = UserService(sessions)
    view, temporary = await service.create(Actor.system(), email, email.split("@")[0], roles)
    if ready:
        await service.change_password(Actor.system(), view.id, temporary, PASSWORD)
        return Account(view.id, view.email), PASSWORD
    return Account(view.id, view.email), temporary


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def escalated_lead(sessions: async_sessionmaker[AsyncSession], tg_user_id: int = 5001) -> int:
    async with sessions() as session, session.begin():
        lead, _, conversation = await repo.create_lead_with_identity(
            session,
            tg_user_id=tg_user_id,
            username="aziz",
            first_name="Азиз",
            chat_id=tg_user_id,
            language="ru",
            identity=None,
        )
        lead.consent_given_at = datetime.now(UTC)
        lead.display_name = "Азиз"
        lead.stage, lead.owner_mode = "handoff", "paused"
        await repo.add_message(
            session, conversation_id=conversation.id, role="lead", text="Сколько стоит?"
        )
        session.add(
            Escalation(lead_id=lead.id, reason_codes=["price_or_contract_asked"], priority="hot")
        )
        return lead.id
