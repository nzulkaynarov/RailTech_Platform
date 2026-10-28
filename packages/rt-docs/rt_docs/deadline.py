"""Тайм-аут рендера: жёсткий (SIGALRM) в главном потоке процесса, мягкий (проверка между проходами) — в остальных.

Мягкий тайм-аут не прерывает проход вёрстки WeasyPrint: сервис, который зовёт рендер не из главного потока
(Procrastinate в EDS гоняет синхронные задачи в потоках, асинхронные — в цикле событий), выносит рендер в отдельный
процесс с kill по тайм-ауту (docs/architecture/rt-docs.md §7, B-094).
"""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .errors import RenderTimeoutError


class Interrupted(BaseException):
    """Сигнал тайм-аута внутри WeasyPrint: BaseException, чтобы его не проглотили `except Exception` движка."""


class Deadline:
    def __init__(self, seconds: float | None) -> None:
        self.seconds = seconds
        self.until = time.monotonic() + seconds if seconds else None
        self._armed = False

    def check(self) -> None:
        """Мягкая проверка между проходами вёрстки."""
        if self.until is not None and time.monotonic() >= self.until:
            raise RenderTimeoutError(self.seconds or 0)

    def _interrupt(self, _signum: int, _frame: Any) -> None:
        if self._armed:  # сигнал, пришедший уже после снятия таймера, ничего не прерывает
            raise Interrupted

    @contextmanager
    def armed(self) -> Iterator[Deadline]:
        """Жёсткий тайм-аут на время блока; `Interrupted` из любой точки (и из выхода блока) → `RenderTimeoutError`."""
        if not self.seconds or threading.current_thread() is not threading.main_thread():
            yield self
            return
        try:
            yield from self._alarm()
        except Interrupted:
            raise RenderTimeoutError(self.seconds) from None

    def _alarm(self) -> Iterator[Deadline]:
        assert self.seconds  # noqa: S101 — проверено в armed()
        previous = signal.signal(signal.SIGALRM, self._interrupt)
        self._armed = True
        outer, _ = signal.setitimer(signal.ITIMER_REAL, self.seconds)
        started = time.monotonic()
        try:
            yield self
        finally:
            # Сначала снять таймер и флаг — потом всё остальное: сигнал в finally не прервёт восстановление.
            self._armed = False
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            if outer:  # чужой таймер процесса — вернуть остаток
                signal.setitimer(signal.ITIMER_REAL, max(0.001, outer - (time.monotonic() - started)))
