"""СЦ-5 (pg): прежний номер находится поиском и по номеру (старая ссылка); разовая перенумерация на латиницу —
сухой прогон не пишет, `--apply` пишет всё разом и повторяется без изменений, столкновения останавливают запись."""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.cli import renumber_cli
from app.container import Container
from app.errors import EdsError
from app.services import instructions, renumber
from tests.domain import Person
from tests.test_letter_duplicates import mark
from tests.test_letter_registration import TAX_NOTICE
from tests.test_registry import fill, listing

pytestmark = pytest.mark.pg

MAPPING = {
    "ВХ-001/26": "IN-001/26",
    "ВХ-002/26": "IN-002/26",
    "ИСХ-001/26": "OUT-001/26",
    "СЗ-2026/001": "MEMO-2026/001",
    "ЗВ-2026-002": "PRJ-2026-002",
}


async def sql(container: Container, statement: str, **params: Any) -> None:
    async with container.session_factory() as session, session.begin():
        await session.execute(text(statement), params)


async def column(container: Container, statement: str) -> list[Any]:
    async with container.session_factory() as session:
        return [tuple(r) if len(r) > 1 else r[0] for r in (await session.execute(text(statement))).all()]


async def to_cyrillic(container: Container, client: httpx.AsyncClient, staff: dict[str, Person]) -> dict[str, Any]:
    """Прод до перенумерации: номера с кириллическим обозначением, копия номера заявки у письма и в заголовке КП."""
    made = await fill(client, container, staff)
    await sql(container, "UPDATE letters SET number = 'ВХ-001/26' WHERE number = 'IN-001/26'")
    await sql(
        container, "UPDATE letters SET number = 'ВХ-002/26', deal_number = 'ЗВ-2026-002' WHERE number = 'IN-002/26'"
    )
    await sql(container, "UPDATE documents SET number = 'ИСХ-001/26' WHERE number = 'OUT-001/26'")
    await sql(container, "UPDATE documents SET number = 'СЗ-2026/001' WHERE number = 'MEMO-2026/001'")
    await sql(
        container,
        "UPDATE approval_routes SET title = 'КП-2026/115 v1 · ЗВ-2026-002', deal_number = 'ЗВ-2026-002' "
        "WHERE template = 'quote'",
    )
    return made


# --- поиск по прежнему номеру -----------------------------------------------------------------------------------


async def test_previous_number_is_found_by_registry_filter_and_search(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await fill(client, container, staff)
    await sql(container, "UPDATE letters SET previous_number = 'ВХ-001/26' WHERE number = 'IN-001/26'")
    await sql(container, "UPDATE documents SET previous_number = 'ИСХ-001/26' WHERE number = 'OUT-001/26'")
    who = staff["manager"]

    async def numbers(**params: Any) -> list[str]:
        return [i["number"] for i in await listing(client, who, **params)]

    assert await numbers(number="ВХ-001/26") == ["IN-001/26"]  # старая ссылка
    assert await numbers(number="ИСХ-001/26") == ["OUT-001/26"]
    assert await numbers(q="ВХ-001") == ["IN-001/26"]
    assert await numbers(q="исх-001") == ["OUT-001/26"]
    assert await numbers(number="ВХ-999/26") == []
    item = (await listing(client, who, number="ВХ-001/26"))[0]
    assert item["number"] == "IN-001/26"

    letters = (await client.get("/api/v1/letters", params={"q": "ВХ-001"}, headers=staff["registrar"].headers)).json()
    assert [i["number"] for i in letters["items"]] == ["IN-001/26"]


async def test_cards_show_previous_number(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    made = await fill(client, container, staff)
    plain = (await client.get(f"/api/v1/letters/{made['l1']['id']}", headers=staff["registrar"].headers)).json()
    assert plain["previous_number"] is None
    await sql(container, "UPDATE letters SET previous_number = 'ВХ-001/26' WHERE number = 'IN-001/26'")
    await sql(container, "UPDATE documents SET previous_number = 'СЗ-2026/001' WHERE number = 'MEMO-2026/001'")
    card = await client.get(f"/api/v1/letters/{made['l1']['id']}", headers=staff["registrar"].headers)
    assert card.json()["previous_number"] == "ВХ-001/26"
    memo = await client.get(f"/api/v1/documents/{made['memo']['id']}", headers=staff["manager"].headers)
    assert memo.json()["previous_number"] == "СЗ-2026/001"


async def test_number_lookups_accept_the_previous_number(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await fill(client, container, staff)
    await sql(container, "UPDATE letters SET previous_number = 'ВХ-001/26' WHERE number = 'IN-001/26'")
    await sql(container, "UPDATE documents SET previous_number = 'ИСХ-001/26' WHERE number = 'OUT-001/26'")
    registrar = staff["registrar"]

    # связь нового входящего с предыдущим — по старому номеру
    body = {**TAX_NOTICE, "sender_ref": {"number": "04-12/3500"}}
    related = await client.post(
        "/api/v1/letters", json={**body, "related_number": "ВХ-001/26"}, headers=registrar.headers
    )
    assert related.status_code == 201, related.text
    assert related.json()["related"]["number"] == "IN-001/26"
    out = await client.post(
        "/api/v1/letters",
        json={**body, "sender_ref": {"number": "04-12/3600"}, "related_number": "ИСХ-001/26"},
        headers=registrar.headers,
    )
    assert out.status_code == 201, out.text
    assert out.json()["related"] == {**out.json()["related"], "kind": "letter_out", "number": "OUT-001/26"}

    # «Исполнено» с номером нашего исходящего — по старому номеру
    async with container.session_factory() as session:
        found = await instructions._outgoing_by_number(session, "ИСХ-001/26")
        assert found.number == "OUT-001/26"
        with pytest.raises(EdsError):
            await instructions._outgoing_by_number(session, "ИСХ-777/26")

    # «Это дубль …» — по старому номеру, без подмены «ВХ»↔«BX» (номер непрозрачен)
    copy = (
        await client.post(
            "/api/v1/letters", json={**body, "force": True, "force_reason": "дубль"}, headers=registrar.headers
        )
    ).json()
    done = await mark(client, registrar, copy["id"], original_number=" вх-001/26 ")
    assert done.status_code == 200, done.text
    assert done.json()["duplicate_of"]["number"] == "IN-001/26"
    again = (
        await client.post("/api/v1/letters", json={**body, "sender_ref": {"number": "9"}}, headers=registrar.headers)
    ).json()
    latin_typo = await mark(client, registrar, again["id"], original_number="BX-001/26")
    assert latin_typo.status_code == 422


# --- перенумерация -------------------------------------------------------------------------------------------


async def test_dry_run_changes_nothing_and_apply_writes_everything_once(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await to_cyrillic(container, client, staff)
    async with container.session_factory() as session, session.begin():
        plan = await renumber.build_plan(session, MAPPING)
    lines = {c.line() for c in plan.changes}
    assert "letters.number " in " ".join(lines) or any(line.startswith("letters.number ") for line in lines)
    assert any(line.endswith("ВХ-001/26 → IN-001/26") for line in lines)
    assert any(
        line.startswith("letters.deal_number ") and line.endswith("ЗВ-2026-002 → PRJ-2026-002") for line in lines
    )
    assert any(
        line.startswith("approval_routes.title ")
        and line.endswith("КП-2026/115 v1 · ЗВ-2026-002 → КП-2026/115 v1 · PRJ-2026-002")
        for line in lines
    )
    assert plan.errors == []
    # сухой прогон только строит план: в базе всё как было
    assert await column(container, "SELECT number FROM letters ORDER BY number") == ["ВХ-001/26", "ВХ-002/26"]
    assert await column(container, "SELECT count(*) FROM letters WHERE previous_number IS NOT NULL") == [0]

    async with container.session_factory() as session, session.begin():
        await renumber.apply_plan(session, await renumber.build_plan(session, MAPPING))
    assert await column(container, "SELECT number, previous_number FROM letters ORDER BY number") == [
        ("IN-001/26", "ВХ-001/26"),
        ("IN-002/26", "ВХ-002/26"),
    ]
    assert await column(
        container,
        "SELECT number, previous_number FROM documents WHERE kind <> 'report' AND number IS NOT NULL ORDER BY number",
    ) == [
        ("MEMO-2026/001", "СЗ-2026/001"),
        ("OUT-001/26", "ИСХ-001/26"),
    ]
    assert await column(container, "SELECT deal_number FROM letters WHERE number = 'IN-002/26'") == ["PRJ-2026-002"]
    assert await column(container, "SELECT title, deal_number FROM approval_routes WHERE template = 'quote'") == [
        ("КП-2026/115 v1 · PRJ-2026-002", "PRJ-2026-002")
    ]

    # повтор: ничего не меняется, прежний номер остаётся первым
    async with container.session_factory() as session, session.begin():
        again = await renumber.build_plan(session, MAPPING)
    assert again.changes == []


async def test_previous_number_keeps_the_earliest(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await to_cyrillic(container, client, staff)
    await sql(container, "UPDATE letters SET previous_number = 'ВХ-0001/26' WHERE number = 'ВХ-001/26'")
    async with container.session_factory() as session, session.begin():
        await renumber.apply_plan(session, await renumber.build_plan(session, MAPPING))
    assert await column(container, "SELECT previous_number FROM letters WHERE number = 'IN-001/26'") == ["ВХ-0001/26"]


async def test_clashes_stop_the_renumbering(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await to_cyrillic(container, client, staff)
    await sql(container, "UPDATE letters SET number = 'IN-005/26' WHERE number = 'ВХ-002/26'")
    async with container.session_factory() as session, session.begin():
        taken = await renumber.build_plan(session, {"ВХ-001/26": "IN-005/26"})
        same = await renumber.build_plan(session, {"ВХ-001/26": "IN-009/26", "СЗ-2026/001": "IN-009/26"})
        with pytest.raises(ValueError, match="IN-005/26"):
            await renumber.apply_plan(session, taken)
    assert any("IN-005/26" in e for e in taken.errors)
    assert any("IN-009/26" in e for e in same.errors)
    assert await column(container, "SELECT number FROM letters ORDER BY number") == ["IN-005/26", "ВХ-001/26"]


async def test_emit_mapping_from_current_labels_and_cli_modes(
    client: httpx.AsyncClient,
    container: Container,
    staff: dict[str, Person],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await to_cyrillic(container, client, staff)
    async with container.session_factory() as session:
        assert await renumber.emit_mapping(session) == {
            "ВХ-001/26": "IN-001/26",
            "ВХ-002/26": "IN-002/26",
            "ИСХ-001/26": "OUT-001/26",
            "СЗ-2026/001": "MEMO-2026/001",
        }
    path = tmp_path / "map.json"
    path.write_text(json.dumps(MAPPING, ensure_ascii=False), encoding="utf-8")

    def args(**kw: Any) -> argparse.Namespace:
        return argparse.Namespace(mapping=str(path), apply=False, emit_mapping=False, **kw)

    capsys.readouterr()
    assert await renumber_cli.run(args(), container) == 0
    dry = capsys.readouterr().out
    assert "letters.number" in dry and "ВХ-001/26 → IN-001/26" in dry and "Сухой прогон" in dry
    assert await column(container, "SELECT count(*) FROM letters WHERE number LIKE 'ВХ%'") == [2]

    assert await renumber_cli.run(args(), container) == 0  # повторный сухой прогон — то же
    applied = args()
    applied.apply = True
    assert await renumber_cli.run(applied, container) == 0
    assert "Записано" in capsys.readouterr().out
    assert await column(container, "SELECT count(*) FROM letters WHERE number LIKE 'ВХ%'") == [0]
    assert await renumber_cli.run(applied, container) == 0  # идемпотентно
    assert "изменений 0" in capsys.readouterr().out
