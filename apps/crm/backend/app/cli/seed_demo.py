"""Демо-данные CRM для dev и e2e: менеджер и лиды в разных состояниях. Идемпотентно."""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.container import get_container
from app.models.leads import Lead, TelegramIdentity
from app.models.qualification import Escalation
from app.repositories import leads as repo
from app.repositories import users as users_repo
from app.security.audit import Actor
from app.services.users import UserService

DEMO_LEADS = [
    # tg_user_id, имя, стадия, owner_mode, score, потребность, эскалация (приоритет, коды)
    (
        900001,
        "Азиз",
        "handoff",
        "paused",
        75,
        "Интеграция 3 касс АТОЛ с 1С",
        ("hot", ["price_or_contract_asked", "callback_requested"]),
    ),
    (900002, "Дилноза", "engaged", "bot", 40, "Мониторинг рефрижераторных контейнеров", None),
    (900003, "Pavel", "qualified", "bot", 60, "RT-Track for 20 wagons", None),
]
DIALOG = [
    ("lead", "Здравствуйте! Сколько стоит подключить 3 кассы к 1С?"),
    ("bot", "Стоимость зависит от числа касс и версии 1С; точный расчёт готовит менеджер."),
    ("lead", "Ок, пусть позвонят, лучше после 15:00"),
]


async def _manager(service: UserService, email: str, password: str) -> None:
    container = get_container()
    async with container.session_factory() as session:
        exists = await users_repo.by_email(session, email)
    if exists is None:
        view, temporary = await service.create(Actor.system(), email, "Демо Менеджер", ["manager"])
        user_id = view.id
    else:
        user_id = exists.id
        temporary = await service.reset_password(Actor.system(), user_id)
    await service.change_password(Actor.system(), user_id, temporary, password)


async def run(args: argparse.Namespace) -> int:
    container = get_container()
    try:
        await _manager(container.user_service, args.manager_email, args.manager_password)
        async with container.session_factory() as session, session.begin():
            for tg_id, name, stage, owner, score, need, escalation in DEMO_LEADS:
                found = await session.scalar(
                    select(TelegramIdentity).where(TelegramIdentity.tg_user_id == tg_id)
                )
                if found is not None:
                    continue
                lead, _, conversation = await repo.create_lead_with_identity(
                    session,
                    tg_user_id=tg_id,
                    username=None,
                    first_name=name,
                    chat_id=tg_id,
                    language="ru",
                    identity=None,
                )
                _fill(lead, name, stage, owner, score, need)
                for role, text in DIALOG:
                    await repo.add_message(
                        session, conversation_id=conversation.id, role=role, text=text
                    )
                if escalation is not None:
                    session.add(
                        Escalation(
                            lead_id=lead.id,
                            priority=escalation[0],
                            reason_codes=escalation[1],
                            recommendation="Позвонить сегодня, уточнить версию 1С",
                        )
                    )
    finally:
        await container.aclose()
    sys.stdout.write("Демо-данные загружены. Менеджер: " + args.manager_email + "\n")
    return 0


def _fill(lead: Lead, name: str, stage: str, owner: str, score: int, need: str) -> None:
    now = datetime.now(UTC)
    lead.display_name, lead.stage, lead.owner_mode, lead.score = name, stage, owner, score
    lead.need_summary, lead.consent_given_at, lead.consent_version = need, now, "demo"
    lead.last_lead_msg_at = now - timedelta(minutes=5)
