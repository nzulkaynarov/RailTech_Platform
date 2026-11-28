"""ТЕСТ-2: запись тестовой компании несёт `is_test: true` — клиент рисует метку «Тестовая».

Поле есть только у таких записей (их видно при «Показывать тестовые»); у остальных его в ответе
нет — форма прежняя.
"""

from typing import Any

from pydantic import BaseModel, model_serializer


class TestTagged(BaseModel):
    __test__ = False  # не тест-класс для pytest

    is_test: bool = False

    @model_serializer(mode="wrap")
    def _omit_unmarked(self, handler: Any) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not data.get("is_test"):
            data.pop("is_test", None)
        return data
