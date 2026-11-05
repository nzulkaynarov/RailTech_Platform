"""«Проверить почту» (MAIL-NOW): опрос общего ящика сразу, а не через ≤ 2 минуты.

Эталон — «Получить сообщения» в Thunderbird и «Отправить и получить» в Outlook. Опрос тот же, что у
плановой задачи (`InboundMailIngest.poll`), под той же блокировкой (`poll_exclusive`): идёт другой
опрос — `checking`, второго чтения ящика нет. Частота — не чаще раза в `MIN_INTERVAL` на
установку (последний опрос, плановый или ручной, хранит `inbound_mailbox.last_poll_at`): раньше —
429 с `Retry-After`. Ждём не дольше `WAIT_S`; опрос дольше (тяжёлые письма) доезжает в фоне, ответ
`checking`, письма появятся в списке сами. Итог — без деталей сервера: только вид ошибки
(`auth_failed`, `unavailable`, …); подробности — в логе. Журнал действий не ведётся.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog

from app.domain.errors import RateLimitedError
from app.schemas.inbound_mail import InboundMailCheckOut
from app.services.inbound_mail_ingest import (
    InboundMailIngest,
    PollBusy,
    PollOutcome,
    PollTooSoon,
)

logger = structlog.get_logger(__name__)

MIN_INTERVAL: Final = timedelta(seconds=20)
WAIT_S: Final = 30.0


class InboundMailCheck:
    def __init__(
        self,
        ingest: InboundMailIngest,
        *,
        min_interval: timedelta = MIN_INTERVAL,
        wait_s: float = WAIT_S,
    ) -> None:
        self._ingest = ingest
        self._min_interval = min_interval
        self._wait_s = wait_s
        self._background: set[asyncio.Task[PollOutcome | PollBusy | PollTooSoon]] = set()

    async def check(self) -> InboundMailCheckOut:
        # Опрос идёт отдельной задачей: не успели за `wait_s` — отвечаем, а он доезжает в фоне.
        task = asyncio.create_task(self._run())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        done, _ = await asyncio.wait({task}, timeout=self._wait_s)
        if not done:
            logger.info("inbound_mail_check_continues")
            return InboundMailCheckOut(status="checking")
        result = task.result()
        if isinstance(result, PollTooSoon):
            raise RateLimitedError(
                "mailbox was checked a moment ago", retry_after_s=result.retry_after_s
            )
        if isinstance(result, PollBusy):
            return InboundMailCheckOut(status="checking")
        return InboundMailCheckOut(
            status=result.status,
            created=result.created,
            error_kind=result.error_kind,
            checked_at=datetime.now(UTC),
        )

    async def _run(self) -> PollOutcome | PollBusy | PollTooSoon:
        try:
            return await self._ingest.poll_exclusive(self._min_interval)
        except Exception:  # сбой базы или хранилища: ответ с видом ошибки, подробности — в логе
            logger.exception("inbound_mail_check_failed")
            return PollOutcome("error", error_kind="internal")
