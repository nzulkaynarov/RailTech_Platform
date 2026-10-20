"""FIX-54: даты в печатных документах — бизнес-дата Ташкента, а не UTC (`TIME_ZONE=Asia/Tashkent`).

Только `DateTimeField` приводятся к местному времени; `DateField` (дата без времени) печатается как есть.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import patch

from crm.services import document_blocks
from crm.services.document_blocks import format_document_date, render_delivery_note_body

LATE_UTC = datetime.datetime(2026, 11, 3, 23, 30, tzinfo=datetime.timezone.utc)  # 04.11 04:30 в Ташкенте


def test_datetime_is_localised_before_formatting():
    assert format_document_date(LATE_UTC) == "04.11.2026"


def test_plain_date_is_printed_as_is():
    assert format_document_date(datetime.date(2026, 11, 3)) == "03.11.2026"


def test_empty_value_is_empty_string():
    assert format_document_date(None) == ""


def test_delivery_note_date_is_the_tashkent_day():
    fulfillment = SimpleNamespace(id=7, note_number="", shipped_at=LATE_UTC, carrier="", tracking_number="")
    template = SimpleNamespace(body_html="{{ doc.date }}")
    with (
        patch.object(document_blocks, "delivery_note_block_values", return_value={}),
        patch.object(document_blocks, "delivery_note_number", return_value="DN-7"),
    ):
        body = render_delivery_note_body(fulfillment, [], "UZS", template)
    assert body == "04.11.2026"
