"""УВЕД-1: текст отчёта об автоотправке КП — каналы словами, не кодами («cabinet, email»)."""

from sales.services.quote_auto_send import _detail


def test_sent_channels_are_words_not_codes() -> None:
    text = _detail({"sent_via": ["cabinet", "email"], "skipped": [], "error": None})
    assert "cabinet" not in text and "email" not in text
    assert text == "Отправлено: в Кабинет, на почту"
