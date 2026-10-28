"""«Подогнать»: подбор плотности, межстрочного и полей, чтобы убрать почти пустую последнюю страницу (аналог Word
«Сократить на страницу»), и «воздух» для короткого письма. Не больше трёх проходов-кандидатов (исследование §3.2).

Пределы — те же, что в схеме тела (`page.tuning`): межстрочный 1,2 … 1,6, поля сверху и снизу уже не больше чем на 6 мм,
отступ до текста 0 … 30 мм. Результат сохраняется в теле (`apply_tuning`) — предпросмотр и выпуск не расходятся.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .css import DENSITY
from .deadline import Deadline, Interrupted
from .errors import RenderTimeoutError
from .model import Density, PageStats, RenderResult, Tuning
from .pdf import DEFAULT_TIMEOUT_S, Prepared, finish, measure

#: Последняя страница заполнена меньше — «почти пустая», её пробуем убрать (документы до трёх страниц).
NEAR_EMPTY = 0.20
#: Одностраничный документ заполнен меньше — короткое письмо «тонет в пустоте», добавляем воздух.
SHORT = 0.40
MAX_PAGES_TO_SHRINK = 3
MAX_EXTRA_RENDERS = 3

_DENSITY_NAMES = {Density.COMPACT: "«Компактно»", Density.NORMAL: "«Обычно»", Density.SPACIOUS: "«Просторно»"}
_SMALLER = {Density.SPACIOUS: Density.NORMAL, Density.NORMAL: Density.COMPACT}


@dataclass(frozen=True)
class FitAction:
    """Что сделала подгонка: код для интерфейса и текст по-русски для журнала и подсказки."""

    code: str  # density | line_height | margins | lead | kept | none
    message: str


@dataclass(frozen=True)
class FitResult:
    result: RenderResult
    before: PageStats
    actions: tuple[FitAction, ...]

    @property
    def passes(self) -> int:
        """Проходов вёрстки всего: исходник, кандидаты (≤ 3) и, если страниц больше одной, проход с номерами страниц."""
        return self.result.passes

    @property
    def tuning(self) -> Tuning:
        return self.result.tuning


def _shrink_candidates(current: Tuning) -> list[tuple[Tuning, list[FitAction]]]:
    """Шаги «сократить», каждый следующий строже: плотность ниже → межстрочный → поля."""
    density = current.density or Density.NORMAL
    _, base_lh = DENSITY[density]
    steps: list[tuple[Tuning, list[FitAction]]] = []
    if density in _SMALLER:
        smaller = _SMALLER[density]
        lh = DENSITY[smaller][1]
        first = Tuning(density=smaller, line_height=None, margin_delta_mm=current.margin_delta_mm, lead_mm=0)
        density_action = FitAction("density", f"Плотность {_DENSITY_NAMES[density]} → {_DENSITY_NAMES[smaller]}")
        steps.append((first, [density_action]))
        tighter = round(max(1.2, lh - 0.1), 2)
        second = replace(first, line_height=tighter)
        lh_action = FitAction("line_height", f"Межстрочный {lh:g} → {tighter:g}")
        steps.append((second, [density_action, lh_action]))
        third = replace(second, margin_delta_mm=-6)
        steps.append((third, [density_action, lh_action, FitAction("margins", "Поля сверху и снизу уже на 6 мм")]))
    else:
        lh = current.line_height or base_lh
        first = replace(current, density=density, line_height=round(max(1.2, lh - 0.1), 2), lead_mm=0)
        lh_action = FitAction("line_height", f"Межстрочный {lh:g} → {first.line_height:g}")
        steps.append((first, [lh_action]))
        second = replace(first, line_height=1.2, margin_delta_mm=-4)
        lh2 = FitAction("line_height", f"Межстрочный {lh:g} → 1.2")
        steps.append((second, [lh2, FitAction("margins", "Поля сверху и снизу уже на 4 мм")]))
        third = replace(second, margin_delta_mm=-6)
        steps.append((third, [lh2, FitAction("margins", "Поля сверху и снизу уже на 6 мм")]))
    return steps


def fit(prepared: Prepared, tuning: Tuning | None = None, *, timeout_s: float | None = DEFAULT_TIMEOUT_S) -> FitResult:
    """Рендер с подгонкой: убрать почти пустую последнюю страницу или дать воздух короткому документу.

    Кандидаты верстаются без номеров страниц (на разбивку они не влияют); проход с «Стр. N из M» — только для итога.
    `timeout_s` — на всю подгонку.
    """
    try:
        return _fit(prepared, tuning, Deadline(timeout_s))
    except Interrupted:  # сигнал на выходе из блока armed(): тоже тайм-аут
        raise RenderTimeoutError(timeout_s or 0) from None


def _fit(prepared: Prepared, tuning: Tuning | None, deadline: Deadline) -> FitResult:
    with deadline.armed():
        base = measure(prepared, tuning, deadline)
        stats = base.stats
        passes = 1
        if 1 < stats.pages <= MAX_PAGES_TO_SHRINK and stats.last_page_fill < NEAR_EMPTY:
            used = replace(base.tuning, density=base.setup.density, line_height=base.setup.line_height)
            for candidate, actions in _shrink_candidates(used)[:MAX_EXTRA_RENDERS]:
                attempt = measure(prepared, candidate, deadline)
                passes += 1
                if attempt.stats.pages < stats.pages:
                    return FitResult(finish(prepared, attempt, deadline, passes), stats, tuple(actions))
            kept = FitAction(
                "kept",
                f"Последнюю страницу ({stats.last_page_fill:.0%}) не убрать в допустимых пределах плотности и полей — "
                f"оставлено {stats.pages} стр.; сократите текст или добавьте разрыв страницы",
            )
            return FitResult(finish(prepared, base, deadline, passes), stats, (kept,))
        if stats.pages == 1 and stats.last_page_fill < SHORT:
            density = base.setup.density
            lead = 20 if stats.last_page_fill < 0.3 else 10
            candidate = Tuning(density=Density.SPACIOUS, line_height=None, margin_delta_mm=0, lead_mm=lead)
            attempt = measure(prepared, candidate, deadline)
            passes += 1
            if attempt.stats.pages == 1:
                actions = []
                if density is not Density.SPACIOUS:
                    actions.append(FitAction("density", f"Плотность {_DENSITY_NAMES[density]} → «Просторно»"))
                actions.append(FitAction("lead", f"Отступ до текста {lead} мм"))
                return FitResult(finish(prepared, attempt, deadline, passes), stats, tuple(actions))
        return FitResult(finish(prepared, base, deadline, passes), stats, (FitAction("none", "Подгонка не нужна"),))


def apply_tuning(body: Mapping[str, Any], tuning: Tuning) -> dict[str, Any]:
    """Копия тела с сохранённым результатом подгонки (`page.density`, `page.tuning`)."""
    out = copy.deepcopy(dict(body))
    page = dict(out.get("page") or {})
    if tuning.density is not None:
        page["density"] = tuning.density.value
    saved = tuning.to_json()
    if tuning.density is not None and tuning.line_height == DENSITY[tuning.density][1]:
        saved.pop("lineHeight", None)  # межстрочный по умолчанию для плотности — не хранится
    if saved:
        page["tuning"] = saved
    else:
        page.pop("tuning", None)
    out["page"] = page
    return out
