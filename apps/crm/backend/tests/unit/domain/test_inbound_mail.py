"""Разбор входящего письма и подсказка помощника (W18A-P2): тексты и адреса — вымышленные."""

from email.message import EmailMessage

import pytest

from app.domain import inbound_mail as im

PDF = b"%PDF-1.4 test"


def _mail(
    *,
    body: str = "Здравствуйте, просим КП на 10 шпал.",
    html: str | None = None,
    message_id: str | None = "<abc-1@example.test>",
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Иван Тестов <Ivan@Example.TEST>"
    msg["To"] = "info@company.test"
    msg["Subject"] = "Запрос КП"
    msg["Date"] = "Mon, 02 Nov 2026 10:00:00 +0500"
    if message_id:
        msg["Message-ID"] = message_id
    msg["In-Reply-To"] = "<prev@example.test>"
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    for name, ctype, data in attachments or []:
        main, _, sub = ctype.partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg.as_bytes()


def test_parse_basic_fields() -> None:
    parsed = im.parse_message(_mail())
    assert parsed.message_id == "abc-1@example.test"
    assert parsed.from_email == "ivan@example.test"
    assert parsed.from_name == "Иван Тестов"
    assert parsed.to == ("info@company.test",)
    assert parsed.subject == "Запрос КП"
    assert parsed.sent_at is not None
    assert parsed.sent_at.utcoffset() is not None
    assert parsed.in_reply_to == "<prev@example.test>"
    assert parsed.text == "Здравствуйте, просим КП на 10 шпал."


def test_message_id_missing_uses_content_fingerprint() -> None:
    raw = _mail(message_id=None)
    first, second = im.parse_message(raw), im.parse_message(raw)
    assert first.message_id.startswith("sha256-")
    assert first.message_id == second.message_id


def test_html_only_body_becomes_safe_text() -> None:
    msg = EmailMessage()
    msg["From"] = "a@example.test"
    msg["Subject"] = "html"
    msg.set_content(
        "<html><head><style>p{color:red}</style></head><body><p>Добрый день</p>"
        "<script>alert(1)</script><p>Счёт &amp; акт</p></body></html>",
        subtype="html",
    )
    parsed = im.parse_message(msg.as_bytes())
    assert parsed.text == "Добрый день\n\nСчёт & акт"
    assert "alert" not in parsed.text
    assert "<" not in parsed.text


def test_plain_preferred_over_html() -> None:
    parsed = im.parse_message(_mail(body="Простой текст", html="<p>HTML</p>"))
    assert parsed.text == "Простой текст"


def test_attachments_whitelist_and_size() -> None:
    big = b"%PDF" + b"0" * (im.MAX_FILE_BYTES + 1)
    parsed = im.parse_message(
        _mail(
            attachments=[
                ("счёт.pdf", "application/pdf", PDF),
                ("virus.exe", "application/octet-stream", b"MZ"),
                ("big.pdf", "application/pdf", big),
                ("scan.bin", "application/octet-stream", PDF),
            ]
        )
    )
    assert [f.name for f in parsed.files] == ["счёт.pdf"]
    assert parsed.files[0].data == PDF
    assert {(s.name, s.reason) for s in parsed.skipped} == {
        ("virus.exe", "type"),
        ("big.pdf", "size"),
        ("scan.bin", "type"),
    }


def test_attachment_type_by_extension_when_octet_stream() -> None:
    parsed = im.parse_message(_mail(attachments=[("act.pdf", "application/octet-stream", PDF)]))
    assert parsed.files[0].content_type == "application/pdf"


def test_attachment_count_limit() -> None:
    files = [(f"f{i}.pdf", "application/pdf", PDF) for i in range(im.MAX_FILES + 2)]
    parsed = im.parse_message(_mail(attachments=files))
    assert len(parsed.files) == im.MAX_FILES
    assert [s.reason for s in parsed.skipped] == ["count", "count"]


def test_find_inns() -> None:
    assert im.find_inns("ИНН 301234567, ИНН 301234567 и 1234567890123") == ["301234567"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"kind": "buyer", "summary": "Просят КП на шпалы"}', ("buyer", "lead")),
        ('{"kind": "official", "summary": "Письмо налоговой"}', ("official", "register")),
        ('{"kind": "supplier_doc", "summary": "Счёт"}', ("supplier_doc", "register")),
        ('{"kind": "other", "summary": "Реклама"}', ("other", "archive")),
    ],
)
def test_parse_assist_action_is_decided_by_code(raw: str, expected: tuple[str, str]) -> None:
    verdict = im.parse_assist(raw)
    assert verdict is not None
    assert (verdict.kind, verdict.action) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"kind": "delete_everything", "summary": "x"}',
        '{"kind": "buyer"}',
        '{"kind": "buyer", "summary": "   "}',
        "[]",
    ],
)
def test_parse_assist_rejects_garbage(raw: str) -> None:
    assert im.parse_assist(raw) is None


def test_reply_headers() -> None:
    assert im.reply_subject("Запрос КП") == "Re: Запрос КП"
    assert im.reply_subject("RE: Запрос") == "RE: Запрос"
    assert im.thread_references("abc@x.test", "<a@x.test>") == "<a@x.test> <abc@x.test>"
    assert im.thread_references("abc@x.test", None) == "<abc@x.test>"
