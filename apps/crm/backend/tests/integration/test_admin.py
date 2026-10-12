"""Администрирование (Фаза 5): KB через API, пробелы, настройки без рестарта, дашборд, аудит."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.models.kb import KbDocument, KbGap
from app.models.qualification import QualifierRun
from app.services.kb.admin import KbAdminService
from app.services.kb.gaps import register_gap
from app.services.kb.search import KbSearchService
from app.services.settings import SettingsService
from tests.fakes import FakeEmbedder
from tests.integration.crm_helpers import escalated_lead, login, make_user
from tests.integration.test_kb_ingest import FakeConverter, make_service

pytestmark = pytest.mark.integration


class Harness:
    def __init__(self, client: TestClient, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.client = client
        self.ingest = make_service(sessions, FakeConverter())
        self.enqueued: list[int] = []

    async def run_ingest(self) -> None:
        for document_id in self.enqueued:
            await self.ingest.ingest(document_id)
        self.enqueued.clear()


@pytest.fixture
def harness(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[Harness]:
    app = create_app(live_settings)
    with TestClient(app) as client:
        h = Harness(client, sessions)

        async def enqueue(document_id: int) -> None:
            h.enqueued.append(document_id)

        container = app.state.container
        container.__dict__["kb_admin"] = KbAdminService(sessions, h.ingest, enqueue)
        container.__dict__["kb_search"] = KbSearchService(sessions, FakeEmbedder())
        yield h


@pytest.fixture
async def admin(sessions: async_sessionmaker[AsyncSession], harness: Harness) -> dict[str, str]:
    account, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    return login(harness.client, account.email, password)


async def test_upload_ingest_and_test_search(harness: Harness, admin: dict[str, str]) -> None:
    created = harness.client.post(
        "/api/v1/kb/documents",
        headers=admin,
        data={"title": "Доставка", "language": "ru"},
        files={
            "file": (
                "delivery.md",
                "Доставка оборудования по Ташкенту бесплатно.".encode(),
                "text/markdown",
            )
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert harness.enqueued == [document_id]
    await harness.run_ingest()
    doc = harness.client.get(f"/api/v1/kb/documents/{document_id}", headers=admin).json()
    assert (doc["ingest_status"], doc["chunk_count"] > 0) == ("done", True)
    chunks = harness.client.get(f"/api/v1/kb/documents/{document_id}/chunks", headers=admin).json()
    assert "Ташкенту" in chunks[0]["content"]
    found = harness.client.post(
        "/api/v1/kb/search", headers=admin, json={"query": "доставка по Ташкенту", "language": "ru"}
    ).json()
    assert found["hits"][0]["document_id"] == document_id
    assert found["min_score"] == 0.7  # калибровка аудита 2026-10-12
    bad = harness.client.post(
        "/api/v1/kb/documents",
        headers=admin,
        data={"title": "x", "language": "ru"},
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert bad.status_code == 422


async def test_deactivate_hides_from_search(
    harness: Harness, admin: dict[str, str], sessions: async_sessionmaker[AsyncSession]
) -> None:
    document_id = harness.client.post(
        "/api/v1/kb/documents/manual",
        headers=admin,
        json={"title": "Склад", "markdown": "Склад работает круглосуточно.", "language": "ru"},
    ).json()["id"]
    await harness.run_ingest()
    patch = harness.client.patch(
        f"/api/v1/kb/documents/{document_id}", headers=admin, json={"is_active": False}
    )
    assert patch.status_code == 200
    found = harness.client.post(
        "/api/v1/kb/search", headers=admin, json={"query": "склад круглосуточно"}
    ).json()
    assert all(h["document_id"] != document_id for h in found["hits"])
    async with sessions() as session:
        doc = await session.get(KbDocument, document_id)
    assert doc is not None
    assert doc.source_type == "manual"


async def test_gap_closed_by_manual_document(
    harness: Harness, admin: dict[str, str], sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session, session.begin():
        gap_id = await register_gap(
            session,
            question="Есть ли доставка в Самарканд?",
            language="ru",
            best_score=0.3,
            lead_id=None,
        )
        other = await register_gap(
            session, question="Какая погода?", language="ru", best_score=0.1, lead_id=None
        )
    assert gap_id is not None
    assert other is not None
    gaps = harness.client.get("/api/v1/kb/gaps", headers=admin).json()
    assert gaps["total"] == 2
    created = harness.client.post(
        "/api/v1/kb/documents/manual",
        headers=admin,
        json={
            "title": "Доставка в регионы",
            "markdown": "Доставка в Самарканд — 2 рабочих дня.",
            "language": "ru",
            "gap_id": gap_id,
        },
    )
    assert created.status_code == 201
    assert harness.client.post(f"/api/v1/kb/gaps/{other}/ignore", headers=admin).status_code == 200
    async with sessions() as session:
        rows = {g.id: g for g in (await session.scalars(select(KbGap))).all()}
    assert rows[gap_id].status == "resolved"
    assert rows[gap_id].resolved_document_id == created.json()["id"]
    assert rows[other].status == "ignored"
    open_gaps = harness.client.get("/api/v1/kb/gaps?status=open", headers=admin).json()
    assert open_gaps["total"] == 0


async def test_settings_apply_without_restart_and_are_audited(
    harness: Harness, admin: dict[str, str], sessions: async_sessionmaker[AsyncSession]
) -> None:
    body = harness.client.get("/api/v1/settings", headers=admin).json()
    texts = body["values"]["texts"]
    assert "greeting" in body["schemas"]["texts"]["properties"]
    texts["greeting"]["ru"] = "Салам! Это {company}."
    saved = harness.client.put("/api/v1/settings/texts", headers=admin, json=texts)
    assert saved.status_code == 200
    service = SettingsService(sessions, ttl_s=0)
    assert (await service.get()).texts.greeting.get("ru", company="RT") == "Салам! Это RT."
    invalid = harness.client.put(
        "/api/v1/settings/kb", headers=admin, json={"min_score": 7, "top_k": 6}
    )
    assert invalid.status_code == 422
    assert "min_score" in invalid.json()["details"]["paths"]
    async with sessions() as session:
        entry = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "settings.update"))
        ).one()
    assert entry.entity_id == "texts"
    assert entry.after is not None
    assert entry.after["greeting"]["ru"].startswith("Салам")


async def test_settings_cache_ttl_is_shared_through_db(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Другой процесс (воркер) видит изменение после TTL кэша без рестарта."""
    clock = [0.0]
    worker = SettingsService(sessions, ttl_s=30, clock=lambda: clock[0])
    assert (await worker.get()).kb.min_score == 0.7
    await SettingsService(sessions).update("kb", {"min_score": 0.6, "top_k": 6}, None)
    assert (await worker.get()).kb.min_score == 0.7  # кэш ещё жив
    clock[0] = 31
    assert (await worker.get()).kb.min_score == 0.6


def _output(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "need_summary": None,
        "product_interest": [],
        "intent": "info",
        "sentiment": "neutral",
        "qualification": {},
        "proposed_stage": "engaged",
        "recommend_escalation": True,
        "escalation_reason": None,
        "confidence": 0.75,
        "next_best_action": "",
    }
    return {**base, **overrides}


async def test_escalation_dry_run(
    harness: Harness, admin: dict[str, str], sessions: async_sessionmaker[AsyncSession]
) -> None:
    lead_id = await escalated_lead(sessions)
    async with sessions() as session, session.begin():
        session.add(
            QualifierRun(
                lead_id=lead_id,
                output=_output(),
                score_before=40,
                score_after=72,
                triggers_fired=["high_score", "qualifier_recommend"],
            )
        )
    current = harness.client.get("/api/v1/settings", headers=admin).json()["values"]["escalation"]
    stricter = {**current, "high_score_threshold": 80, "qualifier_min_confidence": 0.9}
    report = harness.client.post(
        "/api/v1/settings/escalation/dry-run", headers=admin, json=stricter
    ).json()
    assert (report["dialogs"], report["escalated_current"], report["escalated_candidate"]) == (
        1,
        1,
        0,
    )
    assert report["changed"][0]["current"] == ["high_score", "qualifier_recommend"]


async def test_dashboard_and_audit(
    harness: Harness, admin: dict[str, str], sessions: async_sessionmaker[AsyncSession]
) -> None:
    await escalated_lead(sessions)
    viewer, password = await make_user(sessions, "viewer@railtech.uz", ["viewer"])
    viewer_headers = login(harness.client, viewer.email, password)
    assert harness.client.post("/api/v1/dashboard/refresh", headers=admin).status_code == 200
    board = harness.client.get("/api/v1/dashboard?days=7", headers=viewer_headers).json()
    assert board["funnel"] == {"handoff": 1}
    assert board["totals"]["leads_created"] == 1
    assert board["escalation_reasons"] == {"price_or_contract_asked": 1}
    assert board["open_escalations"] == 1
    assert harness.client.get("/api/v1/audit", headers=viewer_headers).status_code == 403
    audit = harness.client.get("/api/v1/audit?action=auth", headers=admin).json()
    assert audit["total"] >= 2
    assert json.dumps(audit["items"][0])  # сериализуется (inet → str)
    assert harness.client.get("/api/v1/kb/documents", headers=viewer_headers).status_code == 403
