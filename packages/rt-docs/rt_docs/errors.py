"""Ошибки rt_docs."""

from __future__ import annotations

from collections.abc import Sequence


class RtDocsError(Exception):
    """Базовая ошибка пакета."""


class ContractsNotFoundError(RtDocsError):
    """Не найден каталог packages/contracts/documents."""


class BodyError(RtDocsError):
    """Тело документа не проходит схему контракта."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            "; ".join(self.problems[:5]) + (f" (+{len(self.problems) - 5})" if len(self.problems) > 5 else "")
        )


class LetterheadError(RtDocsError):
    """Бланк задан неверно (цвет, логотип)."""


class RenderTimeoutError(RtDocsError):
    """Рендер не уложился в тайм-аут (`timeout_s`)."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        super().__init__(f"document rendering exceeded the {seconds:g} s timeout")
