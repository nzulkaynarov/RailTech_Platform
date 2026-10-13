"""Диспатч ТН ВЭД-фич через реальный `run_ai_job`.

Баг, который это закрепляет: обработчики были объявлены `(payload, user_id)`, а диспетчер
зовёт `handler(payload)` — пакетный подбор кодов (T4) и «своими словами» (T3) падали
TypeError'ом в рантайме при полностью зелёных тестах, потому что dispatch-тест существовал
только для enrich. Урок: каждый ключ FEATURE_HANDLERS обязан иметь тест, проходящий через
НАСТОЯЩИЙ вызов задачи, а не через прямой вызов сервиса.
"""

import pytest

from sourcing import tasks_ai
from sourcing.tasks_ai import FEATURE_HANDLERS, run_ai_job

pytestmark = pytest.mark.django_db


def test_hs_classify_dispatches_through_run_ai_job(monkeypatch):
    seen = {}

    def stub(product_ids):
        seen["ids"] = list(product_ids)
        return {"results": []}

    monkeypatch.setattr("catalog.hs_lookup_ai.classify_products", stub)

    result = run_ai_job.run("hs_classify", {"product_ids": [1, 2, 3]})

    assert result == {"results": []}
    assert seen["ids"] == [1, 2, 3]


def test_hs_lookup_dispatches_through_run_ai_job(monkeypatch):
    monkeypatch.setattr("catalog.hs_lookup_ai.lookup_hs_code", lambda text: {"echo": text})

    result = run_ai_job.run("hs_lookup", {"description": "колодка тормозная"})

    assert result == {"echo": "колодка тормозная"}


def test_every_feature_handler_takes_exactly_the_payload():
    """Инвариант диспетчера: handler(payload) — и ничего больше.

    Второй обязательный параметр в любом обработчике означает TypeError в рантайме,
    невидимый юнит-тестам сервисов.
    """
    import inspect

    for feature, handler in FEATURE_HANDLERS.items():
        required = [
            p
            for p in inspect.signature(handler).parameters.values()
            if p.default is inspect.Parameter.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        assert len(required) == 1, f"{feature}: обработчик требует {len(required)} аргументов вместо 1"


def test_module_import_side_effect_guard():
    """`run_ai_job.run` используется в тестах выше — убедимся, что это настоящая задача."""
    assert tasks_ai.run_ai_job.name.endswith("run_ai_job")
