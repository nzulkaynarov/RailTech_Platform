"""Песочница «Проверить бота»: правила хода и невидимость тестовых лидов в CRM (без БД)."""

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.sandbox import chunk_ids, decision_of, sandbox_identity
from app.integrations.llm_usage import UsageEvent, current_kind, kind_scope
from app.repositories import crm, monitoring
from app.services import dashboard
from app.services.llm_usage import DbUsageRecorder

SANDBOX_FILTER = "leads.source != 'sandbox'"
PG = postgresql.dialect()  # type: ignore[no-untyped-call]


class _Result:
    def all(self) -> list[Any]:
        return []

    def mappings(self) -> "_Result":
        return self

    def scalar_one(self) -> int:
        return 0

    def first(self) -> None:
        return None

    def scalar_one_or_none(self) -> None:
        return None


class RecordingSession:
    """Сессия-шпион: запоминает SQL запросов и отвечает пустыми результатами."""

    def __init__(self) -> None:
        self.sql: list[str] = []
        self.added: list[Any] = []

    def _remember(self, stmt: Any) -> None:
        compiled = stmt.compile(dialect=PG, compile_kwargs={"literal_binds": True})
        self.sql.append(str(compiled))

    async def scalars(self, stmt: Any) -> _Result:
        self._remember(stmt)
        return _Result()

    async def execute(self, stmt: Any, *_: Any) -> _Result:
        self._remember(stmt)
        return _Result()

    async def scalar(self, stmt: Any) -> int:
        self._remember(stmt)
        return 0

    def add(self, row: Any) -> None:
        self.added.append(row)

    def begin(self) -> "RecordingSession":
        return self

    async def __aenter__(self) -> "RecordingSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _lead_queries(sql: list[str]) -> list[str]:
    return [q for q in sql if "FROM leads" in q]


@pytest.mark.parametrize("user_id", [1, 7, 12345])
def test_sandbox_identity_never_collides_with_telegram(user_id: int) -> None:
    assert sandbox_identity(user_id) == -user_id < 0


@pytest.mark.parametrize(
    ("metas", "handed_off", "expected"),
    [
        ([{"action": "answer"}], False, "answer"),
        ([{"action": "fallback"}, {"notice": "x"}], False, "fallback"),
        ([{"action": "answer"}], True, "handoff"),
        ([], False, "system"),
        ([{"notice": "x"}], False, "system"),
    ],
)
def test_decision_of(metas: list[dict[str, Any]], handed_off: bool, expected: str) -> None:
    assert decision_of(metas, handed_off) == expected


def test_chunk_ids_dedupes_in_order() -> None:
    metas: list[dict[str, Any]] = [
        {"kb_hits": [{"chunk_id": 3}, {"chunk_id": 1}, {"chunk_id": 3}]},
        {"kb_hits": None},
        {"kb_hits": [{"chunk_id": "bad"}, {"chunk_id": 2}]},
    ]
    assert chunk_ids(metas) == [3, 1, 2]


async def test_leads_list_excludes_sandbox() -> None:
    session = RecordingSession()
    await crm.list_leads(cast(AsyncSession, session), crm.LeadFilter(), 1, 20, 0, "recent")
    queries = _lead_queries(session.sql)
    assert queries
    assert all(SANDBOX_FILTER in q for q in queries)


async def test_inbox_excludes_sandbox() -> None:
    session = RecordingSession()
    await crm.inbox(cast(AsyncSession, session), 1)
    queries = _lead_queries(session.sql)
    assert len(queries) == 3
    assert all(SANDBOX_FILTER in q for q in queries)


async def test_dashboard_funnel_excludes_sandbox() -> None:
    session = RecordingSession()
    await dashboard.build(cast(AsyncSession, session), 7, date(2026, 10, 12))
    queries = _lead_queries(session.sql)
    assert queries
    assert all(SANDBOX_FILTER in q for q in queries)


async def test_daily_report_excludes_sandbox() -> None:
    session = RecordingSession()
    await monitoring.daily_figures(cast(AsyncSession, session), datetime(2026, 10, 11, tzinfo=UTC))
    queries = _lead_queries(session.sql)
    assert queries
    assert all(SANDBOX_FILTER in q for q in queries)


async def test_kind_scope_marks_usage_as_test() -> None:
    session = RecordingSession()
    sessions = cast(async_sessionmaker[AsyncSession], lambda: session)
    recorder = DbUsageRecorder(sessions, None)
    event = UsageEvent("dialog", "dialog-model", "m", 10, 5, 0.001)
    await recorder.record(event)
    with kind_scope("test"):
        assert current_kind() == "test"
        await recorder.record(event)
    assert current_kind() is None
    assert [row.kind for row in session.added] == ["work", "test"]
