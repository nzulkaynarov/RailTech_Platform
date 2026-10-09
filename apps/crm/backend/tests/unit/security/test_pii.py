import pytest

from app.security.pii import langfuse_mask, mask_text, mask_value, structlog_processor


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Позвоните на +998 90 123-45-67", "Позвоните на [number]"),
        ("мой номер 901234567", "мой номер [number]"),
        ("ИНН 305123456 и почта ivan.petrov@mail.uz", "ИНН [number] и почта [email]"),
        ("Карта 4111 1111 1111 1111", "Карта [number]"),
        ("Нужно 3 кассы и 10 трекеров в 2026 году", "Нужно 3 кассы и 10 трекеров в 2026 году"),
        ("Тариф стоит 150 000 сум", "Тариф стоит 150 000 сум"),
    ],
)
def test_mask_text(text: str, expected: str) -> None:
    assert mask_text(text) == expected


def test_mask_nested() -> None:
    assert mask_value({"a": ["x@y.com", 5], "b": ("+998901234567",)}) == {
        "a": ["[email]", 5],
        "b": ("[number]",),
    }


def test_structlog_processor_keeps_safe_keys() -> None:
    event = {"event": "msg +998901234567", "lead_id": 7, "text": "+998901234567"}
    assert structlog_processor(None, "info", event) == {
        "event": "msg +998901234567",
        "lead_id": 7,
        "text": "[number]",
    }


def test_langfuse_mask_signature() -> None:
    assert langfuse_mask(data={"input": "a@b.co"}) == {"input": "[email]"}
