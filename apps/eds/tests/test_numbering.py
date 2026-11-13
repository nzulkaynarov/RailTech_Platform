"""Нумерация реестра (runbook §2.1): форматы, год по Ташкенту, без пропусков и дублей при параллельных созданиях."""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.clock import company_year
from app.container import Container
from app.services.numbering import NumberKind, allocate, format_number
from tests.domain import Person

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "year", "value", "expected"),
    [
        (NumberKind.LETTER_IN, 2026, 104, "IN-104/26"),
        (NumberKind.LETTER_IN, 2026, 1, "IN-001/26"),
        (NumberKind.OUTGOING, 2026, 82, "OUT-082/26"),
        (NumberKind.MEMO, 2026, 31, "MEMO-2026/031"),
        (NumberKind.APPLICATION, 2027, 5, "APP-2027/005"),
        (NumberKind.REPORT, 2026, 1234, "REP-2026/1234"),
        (NumberKind.LETTER_IN, 2026, 1000, "IN-1000/26"),
    ],
)
def test_number_formats(kind: NumberKind, year: int, value: int, expected: str) -> None:
    assert format_number(kind, year, value) == expected


def test_year_follows_company_timezone() -> None:
    # Ташкент = UTC+5: 31 декабря 19:00 UTC — уже 1 января по Ташкенту.
    assert company_year(datetime(2026, 12, 31, 18, 59, tzinfo=UTC)) == 2026
    assert company_year(datetime(2026, 12, 31, 19, 0, tzinfo=UTC)) == 2027


@pytest.mark.pg
async def test_numbers_are_sequential_and_independent_per_kind(container: Container) -> None:
    async with container.session_factory() as session, session.begin():
        assert [await allocate(session, NumberKind.LETTER_IN, T0) for _ in range(3)] == [
            "IN-001/26",
            "IN-002/26",
            "IN-003/26",
        ]
        assert await allocate(session, NumberKind.MEMO, T0) == "MEMO-2026/001"
        assert await allocate(session, NumberKind.OUTGOING, T0) == "OUT-001/26"
        assert await allocate(session, NumberKind.LETTER_IN, T0) == "IN-004/26"


@pytest.mark.pg
async def test_counter_restarts_on_new_year_by_tashkent_time(container: Container) -> None:
    last_2026 = datetime(2026, 12, 31, 18, 59, tzinfo=UTC)
    first_2027 = datetime(2026, 12, 31, 19, 0, tzinfo=UTC)
    async with container.session_factory() as session, session.begin():
        assert await allocate(session, NumberKind.LETTER_IN, last_2026) == "IN-001/26"
        assert await allocate(session, NumberKind.LETTER_IN, first_2027) == "IN-001/27"
        assert await allocate(session, NumberKind.MEMO, first_2027) == "MEMO-2027/001"
        assert await allocate(session, NumberKind.LETTER_IN, last_2026) == "IN-002/26"


@pytest.mark.pg
async def test_rolled_back_creation_does_not_burn_a_number(container: Container) -> None:
    """Откат транзакции создания возвращает счётчик: пропусков нет (отменённый номер не «сгорает» зря)."""
    async with container.session_factory() as session:
        await session.begin()
        assert await allocate(session, NumberKind.LETTER_IN, T0) == "IN-001/26"
        await session.rollback()
    async with container.session_factory() as session, session.begin():
        assert await allocate(session, NumberKind.LETTER_IN, T0) == "IN-001/26"


@pytest.mark.pg
async def test_fifty_parallel_allocations_have_no_gaps_or_duplicates(container: Container) -> None:
    """50 параллельных транзакций на отдельных соединениях, счётчик года ещё не создан: номера 1..50 ровно по разу."""

    async def one() -> str:
        async with container.session_factory() as session, session.begin():
            number = await allocate(session, NumberKind.LETTER_IN, T0)
            await asyncio.sleep(0)  # дать конкурентам войти в транзакцию, пока строка счётчика заблокирована
            return number

    numbers = await asyncio.gather(*(one() for _ in range(50)))
    assert sorted(numbers) == [f"IN-{n:03d}/26" for n in range(1, 51)]


# --- обозначения номеров (задача «Н», решение владельца 2026-11-13) -------------------------------------------------


@pytest.mark.pg
async def test_labels_are_latin_by_default_and_editable_by_the_admin(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    url = "/api/v1/numbering-labels"
    got = (await client.get(url, headers=staff["registrar"].headers)).json()
    year = company_year(datetime.now(UTC)) % 100
    assert {i["kind"]: (i["label"], i["example"]) for i in got["items"]} == {
        "letter_in": ("IN", f"IN-001/{year:02d}"),
        "outgoing": ("OUT", f"OUT-001/{year:02d}"),
        "memo": ("MEMO", f"MEMO-{2000 + year}/001"),
        "application": ("APP", f"APP-{2000 + year}/001"),
        "report": ("REP", f"REP-{2000 + year}/001"),
    }

    assert (
        await client.put(url, json={"labels": {"memo": "SZ"}}, headers=staff["registrar"].headers)
    ).status_code == 403
    saved = await client.put(url, json={"labels": {"memo": " SZ "}}, headers=staff["admin"].headers)
    assert saved.status_code == 200
    assert {i["kind"]: i["label"] for i in saved.json()["items"]}["memo"] == "SZ"

    async with container.session_factory() as session, session.begin():
        number = await allocate(session, NumberKind.MEMO, datetime.now(UTC))
    assert number.startswith("SZ-"), "новый номер — с новым обозначением, счётчик года продолжается"


@pytest.mark.pg
@pytest.mark.parametrize(
    ("labels", "reason"),
    [
        ({"memo": "A B"}, "invalid_label"),
        ({"memo": "A-B"}, "invalid_label"),
        ({"memo": ""}, "invalid_label"),
        ({"nonsense": "X"}, "unknown_kind"),
        ({"memo": "IN"}, "label_taken"),  # нынешнее обозначение входящих
        ({"memo": "ВХ"}, "label_taken"),  # прежнее обозначение входящих: номера ВХ уже выданы
    ],
)
async def test_bad_or_taken_label_is_refused(
    client: httpx.AsyncClient, staff: dict[str, Person], labels: dict[str, str], reason: str
) -> None:
    response = await client.put("/api/v1/numbering-labels", json={"labels": labels}, headers=staff["admin"].headers)
    assert response.status_code == 422
    assert reason in {f["message"] for f in response.json()["details"]["fields"]}
