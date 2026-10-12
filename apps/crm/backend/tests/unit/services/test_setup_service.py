"""Мастер первого запуска: выдача кода, создание админа, 409 после, гонка и ошибки БД."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from structlog.testing import capture_logs

from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.security.audit import Actor
from app.services.setup import SetupService

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


class FakeUsers:
    def __init__(self, admins: int = 0, fail_with: Exception | None = None) -> None:
        self.admins = admins
        self.created: list[str] = []
        self.fail_with = fail_with

    async def count(self) -> int:
        return self.admins

    async def create(self, email: str, name: str, password: str, actor: Actor) -> int:
        await asyncio.sleep(0)
        if self.fail_with is not None:
            raise self.fail_with
        if self.admins:
            raise ConflictError("admin already exists", reason=Reason.SETUP_DONE)
        self.admins += 1
        self.created.append(email)
        return len(self.created)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _service(users: FakeUsers, clock: Clock | None = None) -> SetupService:
    return SetupService(users.count, users.create, clock or Clock())


async def _issued_code(service: SetupService) -> str:
    with capture_logs() as logs:
        assert await service.ensure_code()
    issued = [e for e in logs if e["event"] == "setup_code_issued"]
    assert len(issued) == 1
    return str(issued[0]["setup_code"])


async def test_code_logged_once_while_valid() -> None:
    service = _service(FakeUsers())
    await _issued_code(service)
    with capture_logs() as logs:
        assert not await service.ensure_code()
    assert not logs


async def test_no_code_when_admin_exists() -> None:
    service = _service(FakeUsers(admins=1))
    assert not await service.needs_setup()
    assert not await service.ensure_code()


async def test_creates_admin_then_closes_forever() -> None:
    users = FakeUsers()
    service = _service(users)
    code = await _issued_code(service)
    await service.create_admin(code, "a@railtech.uz", "A", "Sup3rSecretPass")
    assert users.created == ["a@railtech.uz"]
    assert not await service.needs_setup()
    with pytest.raises(ConflictError) as exc:
        await service.create_admin(code, "b@railtech.uz", "B", "Sup3rSecretPass")
    assert exc.value.details["reason"] == Reason.SETUP_DONE.value


async def test_wrong_code_rejected() -> None:
    users = FakeUsers()
    service = _service(users)
    await _issued_code(service)
    with pytest.raises(ValidationFailedError) as exc:
        await service.create_admin("NOPE", "a@railtech.uz", "A", "Sup3rSecretPass")
    assert exc.value.details["reason"] == Reason.SETUP_CODE_INVALID.value
    assert users.created == []


async def test_expired_code_rejected_and_reissued() -> None:
    clock = Clock()
    service = _service(FakeUsers(), clock)
    code = await _issued_code(service)
    clock.now = T0 + timedelta(hours=25)
    with pytest.raises(ValidationFailedError) as exc:
        await service.create_admin(code, "a@railtech.uz", "A", "Sup3rSecretPass")
    assert exc.value.details["reason"] == Reason.SETUP_CODE_EXPIRED.value
    assert await _issued_code(service) != code


async def test_parallel_attempts_create_one_admin() -> None:
    users = FakeUsers()
    service = _service(users)
    code = await _issued_code(service)
    results = await asyncio.gather(
        service.create_admin(code, "a@railtech.uz", "A", "Sup3rSecretPass"),
        service.create_admin(code, "b@railtech.uz", "B", "Sup3rSecretPass"),
        return_exceptions=True,
    )
    assert len(users.created) == 1
    assert sum(isinstance(r, ConflictError) for r in results) == 1


async def test_unique_conflict_from_db_keeps_code_usable() -> None:
    """Админ создан другим процессом (unique/блокировка в БД) → 409, мастер не «зависает»."""
    users = FakeUsers(fail_with=ConflictError("exists", reason=Reason.SETUP_DONE))
    service = _service(users)
    code = await _issued_code(service)
    with pytest.raises(ConflictError):
        await service.create_admin(code, "a@railtech.uz", "A", "Sup3rSecretPass")
    users.fail_with = None
    await service.create_admin(code, "a@railtech.uz", "A", "Sup3rSecretPass")
    assert users.created == ["a@railtech.uz"]
