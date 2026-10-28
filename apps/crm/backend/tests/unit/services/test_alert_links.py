"""Оповещения «Внешних сервисов» ведут ссылкой на «Подключения» Платформы (W15-H8b, B-009)."""

from datetime import timedelta

from app.domain.external_cause import OPEN_LINE, restored_alert
from app.domain.external_incidents import AlertText
from app.services.external_services.alerts import mail_body, telegram_html

URL = "https://platform.example.com/admin/integrations"
ALERT = AlertText("⚠️ Сломано: Почта <b>", ("С 10:00.", OPEN_LINE))


def test_telegram_alert_gets_a_clickable_link_and_stays_escaped() -> None:
    html = telegram_html(ALERT, URL)
    assert '<a href="https://platform.example.com/admin/integrations">' in html
    assert "Платформа → Admin → Подключения</a>" in html
    assert "<b>⚠️ Сломано: Почта &lt;b&gt;</b>" in html  # заголовок не ломает разметку


def test_mail_alert_gets_the_plain_address() -> None:
    body = mail_body(ALERT, URL)
    assert body.splitlines()[-1] == f"Открыть: Платформа → Admin → Подключения: {URL}"


def test_without_a_platform_address_the_text_hint_stays() -> None:
    assert OPEN_LINE in telegram_html(ALERT, None)
    assert mail_body(ALERT, None).splitlines()[-1] == OPEN_LINE


def test_restored_alert_has_the_same_open_line() -> None:
    restored = restored_alert("Почта", timedelta(minutes=20))
    assert restored.lines[-1] == OPEN_LINE
    assert '<a href="' in telegram_html(restored, URL)
