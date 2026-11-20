"""СЦ-3: приглашения в кабинет, не ушедшие без почты, перевыпускаются письмом; сбой одного не
останавливает остальных, считаются принятые."""

from types import SimpleNamespace
from typing import Any

from app.services.portal_invites import PortalInviteService


class Service(PortalInviteService):
    def __init__(self, pending: list[tuple[int, int | None]], broken: int) -> None:
        self.pending = pending
        self.broken = broken
        self.calls: list[tuple[int, str, int | None]] = []

    async def missed(self) -> list[tuple[int, int | None]]:
        return self.pending

    async def resend(self, who: Any, client_id: int, channel: str, contact_id: int | None) -> Any:
        self.calls.append((client_id, channel, contact_id))
        if client_id == self.broken:
            raise RuntimeError("erp is down")
        return SimpleNamespace(sent_via=["email"] if client_id != 3 else [])


async def test_send_missed_resends_by_email_and_counts_accepted() -> None:
    service = Service([(1, 10), (2, None), (3, 30)], broken=2)

    accepted = await service.send_missed(who=object())  # type: ignore[arg-type]

    assert service.calls == [(1, "email", 10), (2, "email", None), (3, "email", 30)]
    assert accepted == 1, "второй упал, третьему письмо не ушло"
