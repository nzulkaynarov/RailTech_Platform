"""Реестр «Все документы» и экспорт (pg): объединение типов, фильтры SPEC §7.3, курсор, поиск по номеру, CSV и XLSX."""

import io
import zipfile
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

import httpx
import pytest

from app.container import Container
from app.services import registry
from tests.conftest import FakeClock
from tests.domain import Person, deliver_erp, erp_event, validate
from tests.test_api_auth import assert_error
from tests.test_documents import create, submit
from tests.test_letters import NEW_LETTER

pytestmark = pytest.mark.pg


async def fill(client: httpx.AsyncClient, container: Container, staff: dict[str, Person]) -> dict[str, Any]:
    """ВХ-001 (клиент 42, менеджер 5), ВХ-002, СЗ (менеджер), ОТ (снабженец), ИСХ (отправлено), КП-2026/115."""
    made: dict[str, Any] = {}
    reg = staff["registrar"].headers
    made["l1"] = (
        await client.post("/api/v1/letters", json={**NEW_LETTER, "manager_crm_user_id": 5}, headers=reg)
    ).json()
    made["l2"] = (
        await client.post(
            "/api/v1/letters",
            json={
                **NEW_LETTER,
                "subject": "Ещё одно письмо",
                "links": {"crm_client_id": 43},
                "sender": {"name": "ООО «Вторая»"},
            },
            headers=reg,
        )
    ).json()
    made["memo"] = await create(client, staff["manager"], subject="Закупка канцтоваров")
    made["report"] = await create(client, staff["supplier"], kind="report", subject="Отчёт по складу")
    await submit(client, staff["supplier"], made["report"]["id"])
    out = await create(
        client, staff["registrar"], kind="letter_out", subject="Ответ клиенту", recipient={"name": "ООО «Пример»"}
    )
    await submit(client, staff["registrar"], out["id"])
    await deliver_erp(client, container, erp_event("erp/quote.ready_for_approval.v1"))
    return made


async def listing(client: httpx.AsyncClient, who: Person, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/registry", params=params, headers=who.headers)
    assert response.status_code == 200, response.text
    page = response.json()
    validate("RegistryPage", page)
    items: list[dict[str, Any]] = page["items"]
    return items


async def test_registry_unites_all_kinds_newest_first(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await fill(client, container, staff)
    items = await listing(client, staff["manager"])
    assert [(i["kind"], i["number"]) for i in items] == [
        ("quote", "КП-2026/115"),
        ("letter_out", "ИСХ-001/26"),
        ("report", "ОТ-2026/001"),
        ("memo", "СЗ-2026/001"),
        ("letter_in", "ВХ-002/26"),
        ("letter_in", "ВХ-001/26"),
    ]
    quote = items[0]
    assert quote["status"] == "open" and quote["links"]["erp_deal_id"] == 905 and quote["links"]["crm_client_id"] == 42
    assert quote["client"] == {"name": "ООО «Пример Логистик»", "inn": None}
    assert items[1]["client"] == {"name": "ООО «Пример»", "inn": None} and items[1]["status"] == "sent"
    letter = items[-1]
    assert letter["responsible"] == {"crm_user_id": 5, "full_name": "Алия Каримова"}
    assert letter["client"]["name"] == "ООО «Пример Логистик»" and letter["links"]["erp_request_id"] == 77
    assert items[2]["responsible"]["crm_user_id"] == 11  # ответственный за отчёт — автор


async def test_registry_requires_registry_read(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for who in ("admin", "registrar", "nobody"):
        assert_error(await client.get("/api/v1/registry", headers=staff[who].headers), 403, "FORBIDDEN")


async def test_registry_filters(client: httpx.AsyncClient, container: Container, staff: dict[str, Person]) -> None:
    await fill(client, container, staff)
    who = staff["accountant"]

    async def numbers(**params: Any) -> list[str]:
        return [i["number"] for i in await listing(client, who, **params)]

    assert await numbers(kind="letter_in") == ["ВХ-002/26", "ВХ-001/26"]
    assert await numbers(kind=["memo", "report"]) == ["ОТ-2026/001", "СЗ-2026/001"]
    assert await numbers(status="on_approval") == ["ОТ-2026/001"]
    assert await numbers(status=["draft", "sent"]) == ["ИСХ-001/26", "СЗ-2026/001"]
    assert await numbers(number="ВХ-001/26") == ["ВХ-001/26"]  # номер с «/» ищется параметром, не путём
    assert await numbers(number="ВХ-999/26") == []
    assert await numbers(q="канцтоваров") == ["СЗ-2026/001"]
    assert await numbers(q="СЗ-2026") == ["СЗ-2026/001"]
    assert await numbers(responsible=5) == ["СЗ-2026/001", "ВХ-001/26"]
    assert await numbers(crm_client_id=43) == ["ВХ-002/26"]
    assert await numbers(crm_client_id=42, kind="quote") == ["КП-2026/115"]
    assert await numbers(q="100%") == [] and await numbers(q="_") == []  # шаблонные символы не работают как маска


async def test_registry_period_uses_tashkent_dates(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], clock: FakeClock
) -> None:
    """31.12 19:30 UTC — уже 01.01 по Ташкенту: документ попадает в период нового года."""
    clock.set(datetime(2026, 12, 31, 19, 30, tzinfo=UTC))
    letter = await client.post("/api/v1/letters", json=NEW_LETTER, headers=staff["registrar"].headers)
    assert letter.json()["number"] == "ВХ-001/27"
    who = staff["manager"]
    assert len(await listing(client, who, date_from="2027-01-01")) == 1
    assert len(await listing(client, who, date_to="2026-12-31")) == 0
    assert len(await listing(client, who, date_from="2027-01-01", date_to="2027-01-01")) == 1


async def test_registry_cursor_pagination_over_the_union(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await fill(client, container, staff)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        params: dict[str, Any] = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await client.get("/api/v1/registry", params=params, headers=staff["manager"].headers)).json()
        seen += [i["number"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["КП-2026/115", "ИСХ-001/26", "ОТ-2026/001", "СЗ-2026/001", "ВХ-002/26", "ВХ-001/26"]
    assert cursor is None


def sheet_rows(content: bytes) -> list[list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))  # noqa: S314 — свой тестовый файл
    return [["".join(t.itertext()) for t in row.findall("m:c", ns)] for row in root.findall(".//m:row", ns)]


async def test_export_csv_and_xlsx_with_filters_and_journal(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await fill(client, container, staff)
    who = staff["accountant"]  # registry.export
    csv_response = await client.get(
        "/api/v1/registry/export", params={"format": "csv", "kind": "letter_in"}, headers=who.headers
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert csv_response.headers["content-disposition"].startswith(
        "attachment; filename*=UTF-8''registry-2026-10-26.csv"
    )
    text = csv_response.content.decode("utf-8-sig").splitlines()
    assert text[0] == "Тип,Номер,Тема,Статус,Зарегистрирован,Ответственный,Клиент,Сделка ERP"
    assert len(text) == 3 and text[1].startswith("letter_in,ВХ-002/26,") and text[2].startswith("letter_in,ВХ-001/26,")

    xlsx = await client.get("/api/v1/registry/export", params={"kind": "memo", "q": "канцтоваров"}, headers=who.headers)
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    rows = sheet_rows(xlsx.content)
    assert rows[0][:3] == ["Тип", "Номер", "Тема"]
    assert rows[1][:4] == ["memo", "СЗ-2026/001", "Закупка канцтоваров", "draft"]
    assert len(rows) == 2

    async with container.session_factory() as session:
        from sqlalchemy import text as sql

        actions = (
            await session.execute(
                sql("SELECT action, by_crm_user_id, comment FROM journal WHERE action = 'registry.export' ORDER BY id")
            )
        ).all()
    assert [(a, b) for a, b, _ in actions] == [("registry.export", 6), ("registry.export", 6)]
    assert [c for _, _, c in actions] == ["csv, строк: 2", "xlsx, строк: 1"]


async def test_export_needs_its_own_permission(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    assert_error(await client.get("/api/v1/registry/export", headers=staff["manager"].headers), 403, "FORBIDDEN")
    bad = await client.get("/api/v1/registry/export", params={"format": "pdf"}, headers=staff["accountant"].headers)
    assert_error(bad, 422, "VALIDATION_FAILED")


async def test_export_too_large_is_rejected(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], monkeypatch: pytest.MonkeyPatch
) -> None:
    await fill(client, container, staff)
    monkeypatch.setattr(registry, "EXPORT_LIMIT", 3)
    response = await client.get("/api/v1/registry/export", headers=staff["accountant"].headers)
    assert_error(response, 422, "VALIDATION_FAILED", reason="export_too_large")
    narrowed = await client.get(
        "/api/v1/registry/export", params={"kind": "letter_in"}, headers=staff["accountant"].headers
    )
    assert narrowed.status_code == 200


async def test_export_neutralizes_formulas(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await create(client, staff["manager"], subject='=HYPERLINK("http://example.invalid")')
    csv_text = (
        await client.get("/api/v1/registry/export", params={"format": "csv"}, headers=staff["accountant"].headers)
    ).content.decode("utf-8-sig")
    assert "'=HYPERLINK" in csv_text
    xlsx = await client.get("/api/v1/registry/export", headers=staff["accountant"].headers)
    assert sheet_rows(xlsx.content)[1][2].startswith("'=HYPERLINK")
