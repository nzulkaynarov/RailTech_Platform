"""Строки прайса, которые ИИ извлёк при проверке (CAT-1): живут в `erp-temp` до «Применить».

Человек утверждает то, что видел: «Применить» загружает ровно строки отчёта проверки, без второго вызова модели (и без
второй оплаты). Ключ — случайный токен, рядом с строками записан сотрудник, который проверял: чужой токен не применить.
Бакет `erp-temp` сам удаляет объекты старше суток (S0-9) — брошенная проверка не копится.
"""

from __future__ import annotations

import json
import re
import uuid

from django.core.files.base import ContentFile

from core.storage import get_temp_storage

_PREFIX = "ai_price_rows/"
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _path(token: str) -> str | None:
    return f"{_PREFIX}{token}.json" if _TOKEN.match(token or "") else None


def save_rows(rows: list, user_id) -> str:
    token = uuid.uuid4().hex
    body = json.dumps({"user_id": user_id, "rows": rows}, ensure_ascii=False).encode("utf-8")
    get_temp_storage().save(_path(token), ContentFile(body))
    return token


def load_rows(token: str) -> dict | None:
    path = _path(token)
    storage = get_temp_storage()
    if path is None or not storage.exists(path):
        return None
    with storage.open(path) as stored:
        return json.loads(stored.read().decode("utf-8"))


def rows_token_owner(token: str):
    data = load_rows(token)
    return data.get("user_id") if data else None


def drop_rows(token: str) -> None:
    path = _path(token)
    if path:
        get_temp_storage().delete(path)
