"""Количество (ADR-0027 п. 9): `Decimal(14, 3)` в базе, в API — число: целое без дробной части (`12`), дробное — с ней
(`12.5`). Строкой «12.500», как деньги, количество не отдаётся: клиенты считают его числом."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

#: Шаг количества — тысячная (0,001 т = 1 кг).
QUANTUM = Decimal("0.001")


def as_qty(value) -> int | float | None:
    """Количество для JSON: целое — `int`, дробное — `float` с тремя знаками; `None` — как есть."""
    if value is None:
        return None
    amount = Decimal(value).quantize(QUANTUM)
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def to_qty(value) -> Decimal:
    """Ввод количества: число или строка с точкой или запятой → `Decimal` с шагом 0,001."""
    try:
        amount = Decimal(str(value).replace(",", ".").replace("\u00a0", "").replace(" ", ""))
        if not amount.is_finite():  # «nan», «inf» — не количество
            raise ValueError("quantity")
        return amount.quantize(QUANTUM)
    except (InvalidOperation, ValueError):
        raise ValueError("quantity") from None


def qty_text(value) -> str:
    """Количество строкой для портального контракта (`string`): «150», «12.5», без хвостовых нулей."""
    number = as_qty(value)
    return "" if number is None else str(number)


def jsonable(params: dict) -> dict:
    """Параметры журнала и событий: `Decimal` количества → число (JSON не знает `Decimal`)."""
    return {key: (as_qty(value) if isinstance(value, Decimal) else value) for key, value in params.items()}


@extend_schema_field({"type": "number", "description": "Количество, до трёх знаков после запятой (ADR-0027 п. 9)"})
class QuantityField(serializers.DecimalField):
    """Поле количества DRF: принимает число до трёх знаков после запятой, отдаёт `as_qty`."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 3)
        kwargs.setdefault("coerce_to_string", False)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return as_qty(value)
