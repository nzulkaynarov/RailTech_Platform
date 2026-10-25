"""Нумерация реестра (runbook §2.1): форматы, год по Ташкенту, без пропусков и дублей при параллельных созданиях."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.clock import company_year
from app.container import Container
from app.services.numbering import NumberKind, allocate, format_number

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "year", "value", "expected"),
    [
        (NumberKind.LETTER_IN, 2026, 104, "ВХ-104/26"),
        (NumberKind.LETTER_IN, 2026, 1, "ВХ-001/26"),
        (NumberKind.OUTGOING, 2026, 82, "ИСХ-082/26"),
        (NumberKind.MEMO, 2026, 31, "СЗ-2026/031"),
        (NumberKind.APPLICATION, 2027, 5, "ЗЯ-2027/005"),
        (NumberKind.REPORT, 2026, 1234, "ОТ-2026/1234"),
        (NumberKind.LETTER_IN, 2026, 1000, "ВХ-1000/26"),
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
            "ВХ-001/26",
            "ВХ-002/26",
            "ВХ-003/26",
        ]
        assert await allocate(session, NumberKind.MEMO, T0) == "СЗ-2026/001"
        assert await allocate(session, NumberKind.OUTGOING, T0) == "ИСХ-001/26"
        assert await allocate(session, NumberKind.LETTER_IN, T0) == "ВХ-004/26"


@pytest.mark.pg
async def test_counter_restarts_on_new_year_by_tashkent_time(container: Container) -> None:
    last_2026 = datetime(2026, 12, 31, 18, 59, tzinfo=UTC)
    first_2027 = datetime(2026, 12, 31, 19, 0, tzinfo=UTC)
    async with container.session_factory() as session, session.begin():
        assert await allocate(session, NumberKind.LETTER_IN, last_2026) == "ВХ-001/26"
        assert await allocate(session, NumberKind.LETTER_IN, first_2027) == "ВХ-001/27"
        assert await allocate(session, NumberKind.MEMO, first_2027) == "СЗ-2027/001"
        assert await allocate(session, NumberKind.LETTER_IN, last_2026) == "ВХ-002/26"


@pytest.mark.pg
async def test_rolled_back_creation_does_not_burn_a_number(container: Container) -> None:
    """Откат транзакции создания возвращает счётчик: пропусков нет (отменённый номер не «сгорает» зря)."""
    async with container.session_factory() as session:
        await session.begin()
        assert await allocate(session, NumberKind.LETTER_IN, T0) == "ВХ-001/26"
        await session.rollback()
    async with container.session_factory() as session, session.begin():
        assert await allocate(session, NumberKind.LETTER_IN, T0) == "ВХ-001/26"


@pytest.mark.pg
async def test_fifty_parallel_allocations_have_no_gaps_or_duplicates(container: Container) -> None:
    """50 параллельных транзакций на отдельных соединениях, счётчик года ещё не создан: номера 1..50 ровно по разу."""

    async def one() -> str:
        async with container.session_factory() as session, session.begin():
            number = await allocate(session, NumberKind.LETTER_IN, T0)
            await asyncio.sleep(0)  # дать конкурентам войти в транзакцию, пока строка счётчика заблокирована
            return number

    numbers = await asyncio.gather(*(one() for _ in range(50)))
    assert sorted(numbers) == [f"ВХ-{n:03d}/26" for n in range(1, 51)]
