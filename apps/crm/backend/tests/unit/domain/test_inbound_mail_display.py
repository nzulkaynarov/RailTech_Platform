"""Показ письма (W18A-P2-4): рассылка, цитата и большие пробелы целиком; адреса вымышленные."""

import base64
import re
from email.message import EmailMessage

from app.domain import inbound_mail as im

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PAD = "&zwnj;&nbsp;" * 150


def _base(subject: str = "Тест") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "Рассылка <news@shop.example.test>"
    msg["To"] = "info@company.test"
    msg["Subject"] = subject
    msg["Message-ID"] = "<display-1@example.test>"
    return msg


def _newsletter() -> bytes:
    msg = _base("Новинки недели")
    msg.set_content("Новинки недели. Откройте письмо в браузере.")
    msg.add_alternative(
        f"<html><head><style>.a{{color:red}}</style></head><body>"
        f'<div style="display:none">Прехедер {PAD}</div>'
        '<table width="600"><tr><td><img src="cid:logo@shop.test" alt="Лого"></td>'
        "<td><h1>Новинки недели</h1></td></tr>"
        '<tr><td colspan="2"><a href="https://shop.example.test/a?x=1">Смотреть</a>'
        '<img src="https://track.example.test/p.gif" width="1" height="1"></td></tr></table>'
        "<script>alert(1)</script></body></html>",
        subtype="html",
    )
    html_part = msg.get_body(preferencelist=("html",))
    assert html_part is not None
    html_part.add_related(
        PNG, maintype="image", subtype="png", cid="<logo@shop.test>", filename="logo.png"
    )
    return msg.as_bytes()


def test_newsletter_html_is_sanitized_and_cid_is_resolved() -> None:
    parsed = im.parse_message(_newsletter())
    assert parsed.html is not None
    assert "<script" not in parsed.html.html
    assert f"data:image/png;base64,{base64.b64encode(PNG).decode()}" in parsed.html.html
    assert parsed.html.remote_images == 1
    assert parsed.html.missing_images == 0
    assert not re.search(r"\ssrc=\"https?:", parsed.html.html)
    assert [(f.content_id, f.inline) for f in parsed.files] == [("logo@shop.test", True)]


def test_newsletter_missing_inline_image_is_placeholder() -> None:
    msg = _base()
    msg.set_content("x")
    msg.add_alternative('<p>Привет</p><img src="cid:nope@x.test" alt="Лого">', subtype="html")
    parsed = im.parse_message(msg.as_bytes())
    assert parsed.html is not None
    assert parsed.html.missing_images == 1
    assert "data-rt-missing" in parsed.html.html


def test_html_only_newsletter_text_has_no_padding_or_hidden_preheader() -> None:
    msg = _base()
    msg.set_content(
        f'<div style="display:none">Прехедер {PAD}</div>'
        "<table><tr><td>Шпала</td><td>10 шт</td></tr>"
        f"</table><p>{PAD}</p><p>&nbsp;</p><p>&nbsp;</p><p>Конец</p>",
        subtype="html",
    )
    parsed = im.parse_message(msg.as_bytes())
    assert "Прехедер" not in parsed.text
    assert "\n\n\n" not in parsed.text
    assert parsed.text == "Шпала 10 шт\n\nКонец"
    assert parsed.html is not None


def test_plain_text_with_huge_blank_gaps() -> None:
    msg = _base()
    gap = "\n \n \n‌\n" * 40
    msg.set_content(f"Добрый день!{gap}Просим счёт.{gap}С уважением, Иван")
    parsed = im.parse_message(msg.as_bytes())
    assert parsed.text == "Добрый день!\n\nПросим счёт.\n\nС уважением, Иван"
    assert parsed.html is None


def test_plain_reply_quote_and_signature_go_to_tail() -> None:
    msg = _base("Re: КП")
    msg.set_content(
        "Спасибо, берём.\n\nOn Mon, 2 Nov 2026 at 10:00, Менеджер <m@company.test> wrote:\n"
        "> Отправляем КП\n> на 10 шпал\n"
    )
    parsed = im.parse_message(msg.as_bytes())
    assert parsed.text == "Спасибо, берём."
    assert parsed.text_tail.startswith("On Mon, 2 Nov 2026")
    assert "> на 10 шпал" in parsed.text_tail


def test_html_only_reply_quote_goes_to_tail() -> None:
    msg = _base("Re: КП")
    msg.set_content(
        '<div>Спасибо, берём.</div><div class="gmail_quote"><div class="gmail_attr">'
        "Пн, 2 нояб. 2026 г. в 10:00, Менеджер &lt;m@company.test&gt; пишет:<br></div>"
        '<blockquote class="gmail_quote">Отправляем КП<br>на 10 шпал</blockquote></div>',
        subtype="html",
    )
    parsed = im.parse_message(msg.as_bytes())
    assert parsed.text == "Спасибо, берём."
    assert "Отправляем КП" in parsed.text_tail
    assert "пишет" in parsed.text_tail


def test_plain_only_mail_has_no_html() -> None:
    msg = _base()
    msg.set_content("Просто текст")
    parsed = im.parse_message(msg.as_bytes())
    assert parsed.html is None
    assert parsed.text_tail == ""
