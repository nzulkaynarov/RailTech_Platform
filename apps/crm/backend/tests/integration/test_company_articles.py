"""Статьи компании на реальной БД (W18A-P5, B-079): права, CRUD, черновик, журнал."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import NotFoundError, ValidationFailedError
from app.main import create_app
from app.models.auth import AuditLog
from app.models.company_articles import CompanyArticle
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.company_articles import CompanyArticleService
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration
BASE = "/api/v1/company-articles"
MINE = "/api/v1/me/company-articles"


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def actions(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_type == "company_article")
            .order_by(AuditLog.id)
        )
        return list(rows.all())


async def test_create_is_a_draft_with_author_and_audit(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = CompanyArticleService(sessions)

    view = await service.create(
        Actor(boss.id), title="  Кто согласует   договор ", body="## Шаги\n\n- юрист", language="ru"
    )

    assert (view.title, view.status, view.language) == ("Кто согласует договор", "draft", "ru")
    assert view.published_at is None
    assert view.created_by_name == "boss"
    assert await service.list_published() == []
    assert await actions(sessions) == ["company_article.create"]


async def test_publish_unpublish_and_update_write_the_journal_without_the_text(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = CompanyArticleService(sessions)
    actor = Actor(boss.id)
    created = await service.create(
        actor, title="Шаблоны", body="Лежат в общей папке", language="ru"
    )

    published = await service.publish(actor, created.id)
    assert (published.status, published.published_at is not None) == ("published", True)
    assert [v.id for v in await service.list_published()] == [created.id]

    edited = await service.update(actor, created.id, title="Шаблоны документов", language="uz")
    assert (edited.title, edited.language, edited.status) == (
        "Шаблоны документов",
        "uz",
        "published",
    )
    assert edited.body == "Лежат в общей папке"

    back = await service.unpublish(actor, created.id)
    assert (back.status, back.published_at) == ("draft", None)
    assert await service.list_published() == []

    assert await actions(sessions) == [
        "company_article.create",
        "company_article.publish",
        "company_article.update",
        "company_article.unpublish",
    ]
    async with sessions() as session:
        rows = (
            await session.scalars(select(AuditLog).where(AuditLog.entity_type == "company_article"))
        ).all()
    assert all("Лежат в общей папке" not in str(r.before) + str(r.after) for r in rows)
    update = next(r for r in rows if r.action == "company_article.update")
    assert (update.before or {}).get("title") == "Шаблоны"
    assert (update.after or {}).get("title") == "Шаблоны документов"


async def test_repeated_publish_is_idempotent_and_does_not_double_the_journal(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = CompanyArticleService(sessions)
    created = await service.create(Actor(boss.id), title="Т", body="Текст")
    first = await service.publish(Actor(boss.id), created.id)
    second = await service.publish(Actor(boss.id), created.id)
    assert first.published_at == second.published_at
    assert (await actions(sessions)).count("company_article.publish") == 1


async def test_delete_removes_the_article_and_keeps_a_journal_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = CompanyArticleService(sessions)
    created = await service.create(Actor(boss.id), title="Старое", body="Текст")

    await service.delete(Actor(boss.id), created.id)

    with pytest.raises(NotFoundError):
        await service.get(created.id)
    with pytest.raises(NotFoundError):
        await service.delete(Actor(boss.id), created.id)
    assert await actions(sessions) == ["company_article.create", "company_article.delete"]
    async with sessions() as session:
        assert (await session.scalars(select(CompanyArticle))).all() == []


async def test_validation_errors_carry_reason_and_field(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    boss, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    service = CompanyArticleService(sessions)
    created = await service.create(Actor(boss.id), title="Т", body="Текст")
    for call, reason, field in [
        (service.create(Actor(boss.id), title=" ", body="x"), "article_title_empty", "title"),
        (service.create(Actor(boss.id), title="x", body=" "), "article_body_empty", "body"),
        (
            service.create(Actor(boss.id), title="x", body="y", language="de"),
            "article_language_unknown",
            "language",
        ),
        (service.update(Actor(boss.id), created.id, body=""), "article_body_empty", "body"),
        (service.list_all(status="archived"), "article_status_unknown", "status"),
    ]:
        with pytest.raises(ValidationFailedError) as caught:
            await call
        assert caught.value.details["reason"] == reason
        assert caught.value.details["field"] == field
    assert (await service.get(created.id)).title == "Т"


async def test_api_reader_sees_only_published_and_cannot_write(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    boss, boss_pw = await make_user(sessions, "boss@railtech.uz", ["admin"])
    reader, reader_pw = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    admin = login(client, boss.email, boss_pw)
    staff = login(client, reader.email, reader_pw)

    draft = client.post(BASE, headers=admin, json={"title": "Черновик", "body": "Пока не готово"})
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"
    ready = client.post(
        BASE,
        headers=admin,
        json={"title": "График отпусков", "body": "Заявка за 14 дней", "language": "ru"},
    ).json()
    assert client.post(f"{BASE}/{ready['id']}/publish", headers=admin).status_code == 200

    mine = client.get(MINE, headers=staff)
    assert mine.status_code == 200
    assert [a["title"] for a in mine.json()["items"]] == ["График отпусков"]
    assert mine.json()["items"][0]["body"] == "Заявка за 14 дней"

    assert client.get(BASE, headers=staff).status_code == 403
    assert client.get(f"{BASE}/{draft.json()['id']}", headers=staff).status_code == 403
    assert client.post(BASE, headers=staff, json={"title": "Т", "body": "Т"}).status_code == 403
    assert (
        client.patch(f"{BASE}/{ready['id']}", headers=staff, json={"title": "Т"}).status_code == 403
    )
    assert client.post(f"{BASE}/{ready['id']}/publish", headers=staff).status_code == 403
    assert client.post(f"{BASE}/{ready['id']}/unpublish", headers=staff).status_code == 403
    assert client.delete(f"{BASE}/{ready['id']}", headers=staff).status_code == 403
    assert client.get(MINE).status_code == 401

    everything = client.get(BASE, headers=admin).json()["items"]
    assert {a["title"] for a in everything} == {"Черновик", "График отпусков"}
    only_drafts = client.get(BASE, params={"status": "draft"}, headers=admin).json()["items"]
    assert [a["title"] for a in only_drafts] == ["Черновик"]
    assert client.get(BASE, params={"status": "x"}, headers=admin).status_code == 422


async def test_api_director_reads_drafts_but_cannot_change_anything(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    boss, boss_pw = await make_user(sessions, "boss@railtech.uz", ["admin"])
    account, password = await make_user(sessions, "director@railtech.uz", ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, ["DIRECTOR"])]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    admin = login(client, boss.email, boss_pw)
    director = login(client, account.email, password)
    draft = client.post(BASE, headers=admin, json={"title": "Черновик", "body": "Текст"}).json()

    assert client.get(BASE, headers=director).status_code == 200
    assert client.get(f"{BASE}/{draft['id']}", headers=director).json()["status"] == "draft"
    assert client.post(BASE, headers=director, json={"title": "Т", "body": "Т"}).status_code == 403
    assert client.post(f"{BASE}/{draft['id']}/publish", headers=director).status_code == 403
    assert client.delete(f"{BASE}/{draft['id']}", headers=director).status_code == 403
    assert client.get(f"{BASE}/{draft['id']}", headers=admin).json()["status"] == "draft"


async def test_api_crud_errors_and_unpublish(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    boss, boss_pw = await make_user(sessions, "boss@railtech.uz", ["admin"])
    admin = login(client, boss.email, boss_pw)

    empty = client.post(BASE, headers=admin, json={"title": "  ", "body": "x"})
    assert empty.status_code == 422
    assert empty.json()["details"] == {"field": "title", "reason": "article_title_empty"}
    too_long = client.post(BASE, headers=admin, json={"title": "x", "body": "я" * 20001})
    assert too_long.status_code == 422
    assert too_long.json()["details"]["reason"] == "article_body_too_long"
    assert (
        client.post(BASE, headers=admin, json={"title": "x", "body": "y", "extra": 1}).status_code
        == 422
    )

    assert client.get(f"{BASE}/999", headers=admin).status_code == 404
    assert client.patch(f"{BASE}/999", headers=admin, json={"title": "x"}).status_code == 404
    assert client.post(f"{BASE}/999/publish", headers=admin).status_code == 404
    assert client.delete(f"{BASE}/999", headers=admin).status_code == 404

    created = client.post(
        BASE, headers=admin, json={"title": "Т", "body": "<script>alert(1)</script>"}
    ).json()
    # Хранится как текст: безопасный показ — забота рендера, но CRM ничего не «чистит» молча.
    assert created["body"] == "<script>alert(1)</script>"
    assert (
        client.post(f"{BASE}/{created['id']}/publish", headers=admin).json()["status"]
        == "published"
    )
    back = client.post(f"{BASE}/{created['id']}/unpublish", headers=admin)
    assert back.json()["status"] == "draft"
    assert client.get(MINE, headers=admin).json()["items"] == []
    assert client.delete(f"{BASE}/{created['id']}", headers=admin).status_code == 204
    assert client.get(f"{BASE}/{created['id']}", headers=admin).status_code == 404
