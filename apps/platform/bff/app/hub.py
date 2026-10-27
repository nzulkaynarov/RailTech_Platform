"""Поток подсказок инвалидации: шина → Redis pub/sub → открытые SSE-соединения (B5, ADR-0014).

BFF не хранит событий и не отдаёт их данные браузеру. Событие шины превращается в подсказку
`{"topics": [...], "reason": "<тип события>"}`: браузер сам перезапрашивает обычные API (с проверкой
прав), поэтому в поток не утекают чужие данные.

Процессов BFF несколько (`uvicorn --workers 2`), а событие шины приходит только в один: обработчик
приёмника публикует подсказку в канал Redis, каждый процесс слушает канал и раздаёт подсказку своим
соединениям. Redis здесь не хранилище: подсказка, потерянная при обрыве, лечится разовым полным
перезапросом (`resync`) после переподключения слушателя; Last-Event-ID не нужен.
"""

import asyncio
import contextlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import structlog
from redis.asyncio import Redis

log = structlog.get_logger()

CHANNEL = "platform:hints"
# Темы подсказок — перечисление `InvalidationTopic` в platform-bff.yaml.
TOPICS: tuple[str, ...] = ("notifications", "counters", "queue", "activity", "messages")
RESYNC_REASON = "resync"

LISTEN_POLL_SECONDS = 1.0
RECONNECT_MIN_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0


@dataclass(frozen=True)
class Hint:
    topics: tuple[str, ...]
    reason: str

    def dumps(self) -> str:
        return json.dumps({"topics": list(self.topics), "reason": self.reason}, ensure_ascii=False)

    @classmethod
    def loads(cls, raw: str | bytes) -> "Hint | None":
        try:
            body = json.loads(raw)
            topics = tuple(t for t in body["topics"] if t in TOPICS)
            reason = str(body["reason"])
        except (ValueError, KeyError, TypeError):
            return None
        return cls(topics, reason) if topics else None


class Stream:
    """Одно SSE-соединение: накапливает подсказки (объединяет темы), пока писатель спит."""

    def __init__(self, sid: str) -> None:
        self.sid = sid
        self._topics: set[str] = set()
        self._reason = ""
        self._wake = asyncio.Event()

    def push(self, hint: Hint) -> None:
        self._topics.update(hint.topics)
        self._reason = hint.reason
        self._wake.set()

    async def wait(self, seconds: float) -> bool:
        """Ждать подсказку; `False` — прошло `seconds` секунд тишины (пора слать heartbeat)."""
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except TimeoutError:
            return False
        return True

    def take(self) -> Hint | None:
        """Забрать накопленное (темы в порядке каталога) и сбросить."""
        self._wake.clear()
        if not self._topics:
            return None
        topics = tuple(t for t in TOPICS if t in self._topics)
        hint = Hint(topics, self._reason)
        self._topics = set()
        return hint


class EventHub:
    """Соединения этого процесса и слушатель канала Redis (запускается с первым соединением)."""

    def __init__(self, get_redis: Callable[[], Redis]) -> None:
        self._get_redis = get_redis
        self._streams: set[Stream] = set()
        self._task: asyncio.Task[None] | None = None

    @property
    def streams(self) -> int:
        return len(self._streams)

    def attach(self, sid: str) -> Stream:
        stream = Stream(sid)
        self._streams.add(stream)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._listen(), name="platform-hub-listener")
        return stream

    def detach(self, stream: Stream) -> None:
        self._streams.discard(stream)

    async def publish(self, hint: Hint) -> None:
        """Подсказка всем процессам BFF (включая этот). Ошибка Redis уходит вызывающему."""
        await self._get_redis().publish(CHANNEL, hint.dumps())

    def deliver(self, hint: Hint) -> None:
        for stream in tuple(self._streams):
            stream.push(hint)

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._streams.clear()

    async def _listen(self) -> None:
        delay = RECONNECT_MIN_SECONDS
        first = True
        while True:
            try:
                pubsub: Any = self._get_redis().pubsub()
                try:
                    await pubsub.subscribe(CHANNEL)
                    delay = RECONNECT_MIN_SECONDS
                    if not first:
                        # Пока слушателя не было, подсказки могли пропасть: один полный перезапрос.
                        self.deliver(Hint(TOPICS, RESYNC_REASON))
                    first = False
                    await self._read(pubsub)
                finally:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — слушатель живёт, пока жив процесс
                log.warning("hub_listener_failed", error=type(exc).__name__, retry_in=delay)
                first = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    async def _read(self, pubsub: Any) -> None:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=LISTEN_POLL_SECONDS
            )
            if message is None or message.get("type") != "message":
                continue
            hint = Hint.loads(message["data"])
            if hint is not None:
                self.deliver(hint)


def merge_topics(*groups: Iterable[str]) -> tuple[str, ...]:
    wanted = {t for group in groups for t in group}
    return tuple(t for t in TOPICS if t in wanted)
