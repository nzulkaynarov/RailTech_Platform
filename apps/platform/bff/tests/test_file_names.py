import datetime as dt

from app.file_names import content_disposition, document_file_name


def test_full_rule() -> None:
    name = document_file_name("Договор поставки", "ДП-12", dt.date(2026, 11, 18), "ООО Ромашка")
    assert name == "Договор поставки № ДП-12 от 18.11.2026 — ООО Ромашка.pdf"


def test_missing_parts_drop_their_words() -> None:
    assert document_file_name("Акт", "5") == "Акт № 5.pdf"
    assert document_file_name("Акт", None, None, None, "png") == "Акт.png"


def test_unsafe_characters_and_extension_are_cleaned() -> None:
    name = document_file_name("Сч/ёт", "1\\2", None, '..\\x"<y>', "exe")
    for bad in ("/", "\\", '"', "<"):
        assert bad not in name
    assert name.endswith(".bin")


def test_disposition_has_ascii_fallback_and_utf8_name() -> None:
    header = content_disposition("Договор № 12.pdf")
    assert header.startswith('attachment; filename="')
    assert header.isascii()
    assert "filename*=UTF-8''%D0%94%D0%BE%D0%B3%D0%BE%D0%B2%D0%BE%D1%80" in header
    assert 'filename="No 12.pdf"' in header
