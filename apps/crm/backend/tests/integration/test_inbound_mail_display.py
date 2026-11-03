"""Показ письма (W18A-P2-4) на Postgres: что хранится и что уходит в лид и помощнику.

Рассылка с HTML и встроенной картинкой, ответ с цитатой, письмо с огромными пробелами. Адреса и
тексты вымышленные.
"""

import base64
from collections.abc import Iterator
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.inbound_mail import InboundMail
from app.models.leads import Lead
from app.services.inbound_mail import InboundMailService
from app.services.inbound_mail_assist import InboundMailAssist, masked_mail
from tests.fake_imap import FakeImapServer
from tests.integration.test_inbound_mail import (
    BUCKET,
    SECRETS_KEY,
    FakeModel,
    Stand,
    _staff,
)

pytestmark = pytest.mark.integration

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PAD = "&zwnj;&nbsp;" * 200


@pytest.fixture
def server() -> Iterator[FakeImapServer]:
    with FakeImapServer() as running:
        yield running


@pytest.fixture
def stand(sessions: async_sessionmaker[AsyncSession], server: FakeImapServer) -> Stand:
    return Stand(sessions, server)


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, server: FakeImapServer
) -> Iterator[tuple[TestClient, Stand]]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        stand = Stand(sessions, server, container.settings_service)
        container.__dict__["inbound_mail"] = InboundMailService(
            sessions,
            container.settings_service,
            container.mail_service,
            stand.storage,
            BUCKET,
            container.imap_connector.configured,
        )
        yield test_client, stand


def _crlf(msg: EmailMessage) -> bytes:
    return msg.as_bytes().replace(b"\n", b"\r\n")


def _newsletter() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Магазин <news@shop.example.test>"
    msg["To"] = "info@company.test"
    msg["Subject"] = "Новинки недели"
    msg["Message-ID"] = "<news-1@example.test>"
    msg.set_content(
        f'<div style="display:none">Прехедер {PAD}</div>'
        '<table width="600"><tr><td><img src="cid:logo@shop.test" alt="Лого"></td>'
        "<td><h1>Новинки недели</h1><p>Шпалы со скидкой</p></td></tr></table>"
        f"<p>{PAD}</p><p>&nbsp;</p><p>&nbsp;</p>"
        '<img src="https://track.example.test/p.gif?u=1" width="1" height="1">'
        "<script>alert(document.cookie)</script>"
        '<a href="javascript:alert(1)" onclick="alert(2)">Отписаться</a>',
        subtype="html",
    )
    msg.add_related(
        PNG, maintype="image", subtype="png", cid="<logo@shop.test>", filename="logo.png"
    )
    return _crlf(msg)


def _reply_with_gaps() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Покупатель <buyer@example.test>"
    msg["To"] = "info@company.test"
    msg["Subject"] = "Re: КП на шпалы"
    msg["Message-ID"] = "<gaps-1@example.test>"
    gap = "\n \n \n‌\n" * 60
    msg.set_content(
        f"Берём 10 шпал.{gap}Доставка в Ташкент.\n\n"
        "On Mon, 2 Nov 2026 at 10:00, Менеджер <m@company.test> wrote:\n"
        "> Секретная цитата прошлой переписки\n\n-- \nИван, ООО Тест\n+998 90 000 00 00"
    )
    return _crlf(msg)


async def _store(stand: Stand, uid: int, raw: bytes) -> int:
    await stand.configure()
    stand.server.box.add(uid, raw)
    await stand.ingest.poll()
    return (await stand.mails())[-1].id


async def test_newsletter_is_stored_sanitized_with_text_without_padding(stand: Stand) -> None:
    await _store(stand, 1, _newsletter())
    (mail,) = await stand.mails()
    assert mail.html_sanitized is not None
    html = mail.html_sanitized
    assert "<script" not in html
    assert "javascript:" not in html
    assert "onclick" not in html
    assert "alert" not in html
    assert ' src="https://' not in html, "внешняя картинка без src до клика"
    assert 'data-rt-src="https://track.example.test/p.gif?u=1"' in html
    assert f"data:image/png;base64,{base64.b64encode(PNG).decode()}" in html
    assert mail.html_remote_images == 1
    assert mail.text == "Новинки недели\n\nШпалы со скидкой\n\nОтписаться"
    assert "Прехедер" not in mail.text
    assert [(a["name"], a["inline"]) for a in mail.attachments] == [("logo.png", True)]


async def test_reply_text_has_no_gaps_quote_or_signature(stand: Stand) -> None:
    await _store(stand, 1, _reply_with_gaps())
    (mail,) = await stand.mails()
    assert mail.text == "Берём 10 шпал.\n\nДоставка в Ташкент."
    assert mail.text_tail.startswith("On Mon, 2 Nov 2026")
    assert "Секретная цитата" in mail.text_tail
    assert "+998 90 000 00 00" in mail.text_tail
    assert mail.html_sanitized is None, "письмо без HTML показывается текстом, как раньше"


async def test_lead_and_assist_get_the_clean_text_only(stand: Stand) -> None:
    mail_id = await _store(stand, 1, _reply_with_gaps())
    who = await stand.principal()
    result = await stand.service().create_lead(who, mail_id)
    async with stand.sessions() as session:
        lead = await session.get(Lead, result.lead_id)
    assert lead is not None
    assert lead.need_summary == "Re: КП на шпалы\n\nБерём 10 шпал.\n\nДоставка в Ташкент."
    assert "цитата" not in (lead.need_summary or "")

    other = await _store_second(stand)
    model = FakeModel('{"type": "client_request", "summary": "Покупатель берёт шпалы"}')
    await InboundMailAssist(stand.sessions, stand.settings, model).suggest(who, other)
    prompt = model.prompts[0]
    assert "Берём 10 шпал" in prompt
    assert "Секретная цитата" not in prompt
    assert "Иван, ООО Тест" not in prompt, "подпись в модель не уходит"
    async with stand.sessions() as session:
        row = await session.get(InboundMail, other)
    assert row is not None
    assert "Секретная цитата" not in masked_mail(row)


async def _store_second(stand: Stand) -> int:
    msg = EmailMessage()
    msg["From"] = "Второй <second@example.test>"
    msg["To"] = "info@company.test"
    msg["Subject"] = "Re: КП на шпалы 2"
    msg["Message-ID"] = "<gaps-2@example.test>"
    msg.set_content(
        "Берём 10 шпал.\n\nOn Mon, 2 Nov 2026 at 10:00, Менеджер <m@company.test> wrote:\n"
        "> Секретная цитата прошлой переписки\n\n-- \nИван, ООО Тест\n"
    )
    stand.server.box.add(2, _crlf(msg))
    await stand.ingest.poll()
    return (await stand.mails())[-1].id


async def test_api_card_carries_html_tail_and_inline_flag(
    client: tuple[TestClient, Stand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, stand = client
    clerk = await _staff(http, sessions, "clerk-view@railtech.uz", "tpl:REGISTRAR")
    mail_id = await _store(stand, 1, _newsletter())
    card = http.get(f"/api/v1/inbound-mail/{mail_id}", headers=clerk).json()
    (message,) = card["messages"]
    assert message["html"] is not None
    assert "<script" not in message["html"]
    assert message["html_remote_images"] == 1
    assert message["text_tail"] == ""
    assert message["text"] == "Новинки недели\n\nШпалы со скидкой\n\nОтписаться"
    assert [(a["name"], a["inline"]) for a in message["attachments"]] == [("logo.png", True)]
    file = http.get(f"/api/v1/inbound-mail/{mail_id}/attachments/0", headers=clerk)
    assert (file.status_code, file.content) == (200, PNG), "встроенная картинка остаётся вложением"
    listing = http.get("/api/v1/inbound-mail", headers=clerk).json()
    assert listing["items"][0]["attachments_count"] == 0, "логотип в теле письма — не вложение"
    assert listing["items"][0]["preview"] == "Новинки недели\n\nШпалы со скидкой\n\nОтписаться"


async def test_old_row_without_html_shows_as_before(
    client: tuple[TestClient, Stand], sessions: async_sessionmaker[AsyncSession]
) -> None:
    http, stand = client
    clerk = await _staff(http, sessions, "clerk-old@railtech.uz", "tpl:REGISTRAR")
    mail_id = await _store(stand, 1, _reply_with_gaps())
    async with sessions() as session, session.begin():
        row = (await stand.mails())[0]
        merged = await session.merge(row)
        merged.html_sanitized, merged.text_tail = None, ""
        merged.text = "Старое письмо\n\n> цитата как была"
    card = http.get(f"/api/v1/inbound-mail/{mail_id}", headers=clerk).json()
    (message,) = card["messages"]
    assert (message["html"], message["text_tail"]) == (None, "")
    assert message["text"] == "Старое письмо\n\n> цитата как была"


async def test_parsing_runs_off_the_event_loop(stand: Stand) -> None:
    """Очистка HTML и разбор цитат — CPU; тяжёлое письмо не должно останавливать цикл воркера."""
    import threading

    from app.domain.inbound_mail import ParsedMail, parse_message
    from app.services import inbound_mail_ingest as ingest

    seen: list[str] = []

    def spy(raw: bytes) -> ParsedMail:
        seen.append(threading.current_thread().name)
        return parse_message(raw)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ingest, "parse_message", spy)
        await _store(stand, 1, _newsletter())
    assert seen
    assert threading.current_thread().name not in seen


async def test_hostile_deep_mail_is_stored_as_text_quickly(stand: Stand) -> None:
    import time

    msg = EmailMessage()
    msg["From"] = "Враг <evil@example.test>"
    msg["To"] = "info@company.test"
    msg["Subject"] = "Глубокое письмо"
    msg["Message-ID"] = "<deep-1@example.test>"
    msg.set_content("<div>" * 60_000 + "Просим КП" + "</i>" * 60_000, subtype="html")
    started = time.perf_counter()
    await _store(stand, 1, _crlf(msg))
    assert time.perf_counter() - started < 10
    (mail,) = await stand.mails()
    assert mail.html_sanitized is None
    assert mail.text == "Просим КП"
