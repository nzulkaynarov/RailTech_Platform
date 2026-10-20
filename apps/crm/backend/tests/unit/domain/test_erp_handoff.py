"""Ключ идемпотентности передачи клиента (FIX-31, I-5): детерминирован, зависит от тела."""

import uuid

from app.domain.erp_handoff import handoff_idempotency_key

BODY = {"crm_client_id": 7, "company": {"name": "ООО Тест", "inn": "123456789"}, "contacts": [1, 2]}


def test_key_is_a_valid_uuid() -> None:
    assert str(uuid.UUID(handoff_idempotency_key(7, BODY))) == handoff_idempotency_key(7, BODY)


def test_same_client_and_body_give_the_same_key_between_attempts() -> None:
    """Повтор после таймаута шлёт тот же ключ — ERP отвечает тем же, а не создаёт второго."""
    reordered = {
        "contacts": [1, 2],
        "company": {"inn": "123456789", "name": "ООО Тест"},
        "crm_client_id": 7,
    }
    assert handoff_idempotency_key(7, BODY) == handoff_idempotency_key(7, reordered)


def test_key_differs_per_client() -> None:
    assert handoff_idempotency_key(7, BODY) != handoff_idempotency_key(8, BODY)


def test_changed_body_gets_another_key_so_erp_does_not_answer_idempotency_conflict() -> None:
    changed = {**BODY, "contacts": [1, 2, 3]}
    assert handoff_idempotency_key(7, BODY) != handoff_idempotency_key(7, changed)


def test_key_is_not_random() -> None:
    assert len({handoff_idempotency_key(7, BODY) for _ in range(20)}) == 1
