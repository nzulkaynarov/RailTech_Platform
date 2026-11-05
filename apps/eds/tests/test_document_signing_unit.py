"""Модульные тесты шага подписи, кода проверки и печатных реквизитов (SIGN-3, ADR-0024)."""

from datetime import date

from app.services import documents, renders
from app.services.signing_resolve import basis_text


def test_verification_code_format_and_entropy() -> None:
    codes = {documents.generate_verification_code() for _ in range(100)}
    assert len(codes) == 100  # нет коллизий в выборке
    for code in codes:
        assert len(code) == 10
        # Проверяем отсутствие неоднозначных символов
        assert not any(c in code for c in "01OIL")
        assert code.isalnum() and code.isupper()


def test_basis_text_formulations() -> None:
    # Устав — без отметки
    assert basis_text("charter", None, None, None) is None
    # Приказ
    assert basis_text("order", "42-П", date(2026, 2, 1), None) == "Действует на основании приказа № 42-П от 01.02.2026"
    # Доверенность со сроком
    assert (
        basis_text("power_of_attorney", "Д-14/26", date(2026, 1, 15), date(2026, 12, 31))
        == "Действует по доверенности № Д-14/26 от 15.01.2026 (до 31.12.2026)"
    )


def test_with_signature_includes_basis() -> None:
    body = {"doc": {"type": "doc", "content": []}}
    # Без основания
    signed_no_basis = renders._with_signature(body, "А. Т. Рахимов", "Директор")
    parties = signed_no_basis["doc"]["content"][0]["attrs"]["parties"]
    assert parties[0] == {"position": "Директор", "name": "А. Т. Рахимов"}

    # С основанием по доверенности
    signed_with_basis = renders._with_signature(
        body,
        "Б. Х. Каримов",
        "Заместитель директора",
        basis_text="Действует по доверенности № 5 от 10.01.2026",
    )
    parties = signed_with_basis["doc"]["content"][0]["attrs"]["parties"]
    assert parties[0] == {
        "position": "Заместитель директора",
        "name": "Б. Х. Каримов",
        "basis": "Действует по доверенности № 5 от 10.01.2026",
    }
