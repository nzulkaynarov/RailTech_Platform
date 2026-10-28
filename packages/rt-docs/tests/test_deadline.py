"""Тайм-аут рендера (rt_docs.deadline): жёсткий в главном потоке, без «висящего» таймера после выхода."""

from __future__ import annotations

import signal
import threading
import time

import pytest

from rt_docs.deadline import Deadline
from rt_docs.errors import RenderTimeoutError


def busy(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pass


def test_hard_timeout_interrupts_and_leaves_no_timer() -> None:
    deadline = Deadline(0.05)
    with pytest.raises(RenderTimeoutError, match="timeout"), deadline.armed():
        busy(2)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) in (signal.SIG_DFL, signal.default_int_handler, None) or callable(
        signal.getsignal(signal.SIGALRM)
    )


def test_fast_work_finishes_and_timer_is_disarmed() -> None:
    deadline = Deadline(5)
    with deadline.armed():
        busy(0.01)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    busy(0.05)  # таймер снят — ни сигнала, ни исключения


def test_outer_timer_is_restored() -> None:
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        with Deadline(5).armed():
            busy(0.01)
        remaining, _ = signal.getitimer(signal.ITIMER_REAL)
        assert 25 < remaining <= 30
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def test_soft_deadline_in_other_threads() -> None:
    errors: list[BaseException] = []

    def work() -> None:
        deadline = Deadline(0.01)
        try:
            with deadline.armed():
                busy(0.05)
                deadline.check()
        except RenderTimeoutError as error:
            errors.append(error)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert len(errors) == 1
