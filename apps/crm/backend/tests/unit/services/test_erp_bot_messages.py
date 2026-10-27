"""Тексты бота по событиям ERP: настройки, три языка, кнопки (FIX-34, I-8)."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.settings import AppSettings, CompanySettings, TextsSettings
from app.schemas.settings_base import LANGUAGES, Language, LocalizedText
from app.services.erp_bot_messages import (
    DELIVERY_STATUSES,
    BotMessage,
    client_message,
    feed_note,
    pick_language,
    staff_alert,
)

TEXTS = TextsSettings()
CABINET = "https://cabinet.example.com"

PAYLOADS: dict[str, dict[str, Any]] = {
    "quote.sent": {"erp_quote_id": 42, "version": 1, "public_url": "https://erp.example.com/q/42"},
    "invoice.issued": {
        "number": "INV-7",
        "amount": "1000.00",
        "currency": "UZS",
        "due_date": "2026-10-30",
        "link": "https://cabinet.example.com/invoices/7",
    },
    "invoice.paid": {"number": "INV-7", "amount": "1000.00", "currency": "UZS"},
    "delivery.status_changed": {"line_summary": "Колёса", "status": "shipped"},
    "delivery.eta_changed": {"line_summary": "Колёса", "eta": "2026-11-05"},
    "act.issued": {"number": "ACT-3"},
}
# Что обязано оказаться в тексте любой локали: значения из payload и сделки.
MUST_CONTAIN: dict[str, list[str]] = {
    "quote.sent": ["Оси РУ1Ш"],
    "invoice.issued": ["INV-7", "1000.00", "UZS", "2026-10-30"],
    "invoice.paid": ["INV-7", "1000.00", "UZS"],
    "delivery.status_changed": ["Оси РУ1Ш", "Колёса"],
    "delivery.eta_changed": ["Оси РУ1Ш", "Колёса", "2026-11-05"],
    "act.issued": ["ACT-3"],
}


def render(event: str, language: Language, *, cabinet_url: str = CABINET) -> BotMessage:
    message = client_message(
        event,
        PAYLOADS[event],
        deal_title="Оси РУ1Ш",
        texts=TEXTS,
        language=language,
        cabinet_url=cabinet_url,
    )
    assert message is not None
    return message


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("event", sorted(PAYLOADS))
def test_every_event_renders_in_every_language(event: str, language: Language) -> None:
    message = render(event, language)
    assert message.text
    assert "{" not in message.text
    assert "}" not in message.text
    for value in MUST_CONTAIN[event]:
        assert value in message.text


@pytest.mark.parametrize("event", sorted(PAYLOADS))
def test_languages_differ_and_ru_is_russian(event: str) -> None:
    texts = {language: render(event, language).text for language in LANGUAGES}
    assert len(set(texts.values())) == 3
    assert any("а" <= ch.lower() <= "я" for ch in texts["ru"].replace("Колёса", ""))
    assert not any(
        "а" <= ch.lower() <= "я" for ch in texts["en"].replace("Оси РУ1Ш", "").replace("Колёса", "")
    )


@pytest.mark.parametrize(
    ("language", "quote", "invoice", "cabinet"),
    [
        ("ru", "Открыть КП", "Открыть счёт", "Кабинет"),
        ("uz", "Taklifni ochish", "Hisobni ochish", "Kabinet"),
        ("en", "Open the quote", "Open the invoice", "Cabinet"),
    ],
)
def test_buttons_are_localized(language: Language, quote: str, invoice: str, cabinet: str) -> None:
    assert render("quote.sent", language).buttons == (
        (quote, "https://erp.example.com/q/42"),
        (cabinet, CABINET),
    )
    assert render("invoice.issued", language).buttons == (
        (invoice, "https://cabinet.example.com/invoices/7"),
        (cabinet, CABINET),
    )


def test_cabinet_button_only_when_configured() -> None:
    """Пустой адрес Cabinet — сообщение и кнопка документа на месте, кнопки «Кабинет» нет."""
    message = render("quote.sent", "ru", cabinet_url="")
    assert message.buttons == (("Открыть КП", "https://erp.example.com/q/42"),)
    assert render("invoice.paid", "ru", cabinet_url="").buttons == ()
    assert render("invoice.paid", "ru").buttons == (("Кабинет", CABINET),)


@pytest.mark.parametrize("bad_url", ["", "javascript:alert(1)", "not a url", "ftp://x.example.com"])
def test_bad_event_url_does_not_break_the_message(bad_url: str) -> None:
    payload = {**PAYLOADS["quote.sent"], "public_url": bad_url}
    message = client_message(
        "quote.sent",
        payload,
        deal_title="Оси",
        texts=TEXTS,
        language="ru",
        cabinet_url=CABINET,
    )
    assert message is not None
    assert message.buttons == (("Кабинет", CABINET),)  # без кнопки КП, текст уходит


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("status", DELIVERY_STATUSES)
def test_delivery_status_is_human_readable(language: Language, status: str) -> None:
    message = client_message(
        "delivery.status_changed",
        {"line_summary": "Колёса", "status": status},
        deal_title="Оси",
        texts=TEXTS,
        language=language,
        cabinet_url="",
    )
    assert message is not None
    assert status not in message.text  # код статуса клиенту не показываем


def test_unknown_delivery_status_is_kept_as_is() -> None:
    message = client_message(
        "delivery.status_changed",
        {"line_summary": "Колёса", "status": "teleported"},
        deal_title="Оси",
        texts=TEXTS,
        language="ru",
        cabinet_url="",
    )
    assert message is not None
    assert "teleported" in message.text


@pytest.mark.parametrize(
    "event",
    [
        "request.created",
        "deal.stage_changed",
        "quote.viewed",
        "quote.accepted",
        "quote.rejected",
        "contract.signed",
        "invoice.overdue",
        "act.accepted",
        "act.returned",
        "deal.won",
        "deal.lost",
        "document.created",
        "invite.sent",
        "delivery.line_accepted",
        "delivery.line_disputed",
    ],
)
def test_other_events_do_not_message_the_client(event: str) -> None:
    assert (
        client_message(event, {}, deal_title="Оси", texts=TEXTS, language="ru", cabinet_url=CABINET)
        is None
    )


def test_text_override_from_settings_wins() -> None:
    """Админ поменял текст в «Настройках» — бот говорит новым текстом."""
    texts = TextsSettings(
        erp_act_issued=LocalizedText(
            ru="Готов акт {number}.", uz="{number}-dalolatnoma tayyor.", en="Act {number} is ready."
        )
    )
    message = client_message(
        "act.issued", {"number": "ACT-3"}, deal_title="", texts=texts, language="en", cabinet_url=""
    )
    assert message is not None
    assert message.text == "Act ACT-3 is ready."


def test_override_with_wrong_placeholders_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TextsSettings(
            erp_act_issued=LocalizedText(ru="Акт {nomer}", uz="{number}", en="Act {number}")
        )


def test_staff_alerts_are_russian_and_filled() -> None:
    accepted = staff_alert(
        "quote.accepted",
        {"erp_quote_id": 42},
        client_name="ООО Тест",
        deal_title="Оси",
        texts=TEXTS,
    )
    returned = staff_alert(
        "act.returned",
        {"number": "ACT-3", "reason": "Нет печати"},
        client_name="ООО Тест",
        deal_title="Оси",
        texts=TEXTS,
    )
    assert accepted is not None
    assert "ООО Тест" in accepted
    assert "#42" in accepted
    assert returned is not None
    assert "ACT-3" in returned
    assert "Нет печати" in returned
    assert "{" not in accepted + returned


def test_staff_alert_only_for_three_events() -> None:
    for event in (
        "quote.sent",
        "invoice.paid",
        "deal.won",
        "act.issued",
        "delivery.line_accepted",  # приёмка — решение клиента, менеджеру личное сообщение не нужно
    ):
        assert staff_alert(event, {}, client_name="X", deal_title="Y", texts=TEXTS) is None


@pytest.mark.parametrize(
    ("raw", "expected"), [("ru", "ru"), ("uz", "uz"), ("en", "en"), ("de", "ru"), (None, "ru")]
)
def test_language_falls_back_to_russian(raw: str | None, expected: str) -> None:
    assert pick_language(raw) == expected


@pytest.mark.parametrize("value", ["https://cabinet.example.com", "", "  http://c.example.com  "])
def test_cabinet_url_setting_accepts_empty_and_http(value: str) -> None:
    assert CompanySettings(cabinet_url=value).cabinet_url == value.strip()


@pytest.mark.parametrize("value", ["cabinet.example.com", "javascript:alert(1)", "ftp://c.example"])
def test_cabinet_url_setting_rejects_garbage(value: str) -> None:
    with pytest.raises(ValidationError):
        CompanySettings(cabinet_url=value)


def test_cabinet_url_default_is_empty_and_lives_in_company() -> None:
    assert AppSettings().company.cabinet_url == ""


@pytest.mark.parametrize("language", LANGUAGES)
def test_empty_texts_and_button_labels_fall_back_to_defaults(language: Language) -> None:
    """Пустой текст или подпись кнопки Telegram отклонил бы — берём значение по умолчанию."""
    blank = LocalizedText(ru="", uz=" ", en="")
    # model_copy не валидирует: так выглядят уже сохранённые настройки с пустым значением.
    texts = TEXTS.model_copy(
        update={
            "erp_quote_sent": blank,
            "erp_btn_quote": blank,
            "erp_btn_cabinet": blank,
            "erp_delivery_statuses": blank,
        }
    )
    quote = client_message(
        "quote.sent",
        PAYLOADS["quote.sent"],
        deal_title="Оси РУ1Ш",
        texts=texts,
        language=language,
        cabinet_url=CABINET,
    )
    assert quote is not None
    assert quote.text.strip()
    assert quote.text == render("quote.sent", language).text
    assert quote.buttons == render("quote.sent", language).buttons
    assert all(label.strip() for label, _ in quote.buttons)
    status = client_message(
        "delivery.status_changed",
        PAYLOADS["delivery.status_changed"],
        deal_title="Оси",
        texts=texts,
        language=language,
        cabinet_url="",
    )
    assert status is not None
    assert "shipped" not in status.text


LINE_PAYLOAD: dict[str, Any] = {
    "line_no": 2,
    "title": "Труба 89х4 ст20",
    "status": "disputed",
    "remark": "Часть труб с трещинами",
    "decided_at": "2026-10-20T10:00:00+05:00",
}


def test_staff_alert_for_a_disputed_delivery_line_has_the_remark() -> None:
    text = staff_alert(
        "delivery.line_disputed",
        LINE_PAYLOAD,
        client_name="ООО Тест",
        deal_title="Оси",
        texts=TEXTS,
    )
    assert text is not None
    for part in ("ООО Тест", "Оси", "Труба 89х4 ст20", "Часть труб с трещинами", "2"):
        assert part in text
    assert "{" not in text


@pytest.mark.parametrize(
    ("event", "needle"),
    [("delivery.line_accepted", "принял"), ("delivery.line_disputed", "оспорил")],
)
def test_feed_note_for_delivery_lines_comes_from_settings(event: str, needle: str) -> None:
    note = feed_note(event, LINE_PAYLOAD, contact_name="Азамат", deal_title="Оси", texts=TEXTS)
    assert note is not None
    assert needle in note
    assert "Азамат" in note
    assert "Труба 89х4 ст20" in note
    assert "{" not in note
    if event == "delivery.line_disputed":
        assert "Часть труб с трещинами" in note


def test_feed_note_override_and_missing_contact_name() -> None:
    texts = TextsSettings(
        erp_note_delivery_line_accepted=LocalizedText(
            ru="Принято: {title} №{line} ({contact}) — {deal}",
            uz="Qabul: {title} №{line} ({contact}) — {deal}",
            en="Accepted: {title} #{line} ({contact}) — {deal}",
        )
    )
    note = feed_note(
        "delivery.line_accepted", LINE_PAYLOAD, contact_name=None, deal_title="Оси", texts=texts
    )
    assert note == "Принято: Труба 89х4 ст20 №2 (контакт клиента) — Оси"


def test_feed_note_is_only_for_delivery_line_events() -> None:
    for event in ("quote.accepted", "delivery.status_changed", "act.returned"):
        assert feed_note(event, {}, contact_name="X", deal_title="Y", texts=TEXTS) is None


def test_delivery_line_texts_reject_wrong_placeholders() -> None:
    with pytest.raises(ValidationError):
        TextsSettings(
            erp_staff_delivery_line_disputed=LocalizedText(
                ru="Оспорено: {zamechanie}", uz="{remark}", en="Disputed: {remark}"
            )
        )


@pytest.mark.parametrize(
    ("channels", "sends"),
    [
        (None, True),  # отправка менеджером — все каналы клиента, как прежде
        (["telegram", "cabinet"], True),
        (["telegram"], True),
        (["cabinet", "email"], False),  # ERP-11: директор не выбрал Telegram — бот молчит
        ([], False),
    ],
)
def test_quote_sent_goes_to_telegram_only_when_chosen(
    channels: list[str] | None, sends: bool
) -> None:
    payload = dict(PAYLOADS["quote.sent"])
    if channels is not None:
        payload["channels"] = channels
    message = client_message(
        "quote.sent", payload, deal_title="Оси", texts=TEXTS, language="ru", cabinet_url=CABINET
    )
    assert (message is not None) is sends


# ── «Заявка принята, считаем» (D1-9, SPEC-v3 §3.1 шаг 2 и Приложение Б) ───────────────────────────


def accepted(
    source: str, language: Language = "ru", *, number: str = "ЗВ-2026-007", url: str = CABINET
) -> BotMessage | None:
    return client_message(
        "request.created",
        {"source": source, "erp_request_id": 7},
        deal_title="Заявка: ООО Рельс",
        texts=TEXTS,
        language=language,
        cabinet_url=url,
        deal_number=number,
    )


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("source", ["crm", "cabinet"])
def test_request_created_tells_the_client_with_number_and_cabinet_button(
    source: str, language: Language
) -> None:
    message = accepted(source, language)
    assert message is not None
    assert "ЗВ-2026-007" in message.text
    assert [url for _, url in message.buttons] == [CABINET]
    assert message.buttons[0][0] in {"Открыть кабинет", "Kabinetni ochish", "Open account"}


def test_request_created_by_staff_in_erp_is_not_announced_to_the_client() -> None:
    assert accepted("erp") is None


def test_request_created_without_cabinet_url_has_no_button() -> None:
    message = accepted("crm", url="")
    assert message is not None
    assert message.buttons == ()


def test_request_created_without_number_still_reads_well() -> None:
    message = accepted("crm", number="")
    assert message is not None
    assert message.text.startswith("Заявка принята")


def test_request_created_text_has_no_internal_terms() -> None:
    message = accepted("crm")
    assert message is not None
    for word in ("лид", "сделк", "crm", "CRM"):
        assert word not in message.text
