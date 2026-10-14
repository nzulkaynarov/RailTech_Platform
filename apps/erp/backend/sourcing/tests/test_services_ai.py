"""Разбор файла клиента в строки запроса — чистая логика и устойчивость одного вызова.

Нормализация (`normalize_items`) — без I/O; устойчивость вызова (отказ модели, оборванный и
непарсибельный JSON, недоступный шлюз) и политика повторов — через фейковый шлюз LiteLLM
(`fake_gateway`), без единого настоящего вызова модели.
"""

import pytest
from ai.services.intake import extract_request_items
from ai.services.intake import normalize_items as _normalize_items
from django.test import SimpleTestCase

VALID_CODES = {"PCE", "MTR", "KGM"}


@pytest.fixture
def no_units(monkeypatch):
    monkeypatch.setattr("ai.services.intake.unit_code_reference", lambda: (set(), ""))


class NormalizeItemsTest(SimpleTestCase):
    def test_drops_fully_empty_rows(self):
        items = [{"name": "", "mpn": "", "gost_drawing": ""}, {"name": "Болт М12"}]
        result = _normalize_items(items, VALID_CODES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Болт М12")

    def test_keeps_code_only_rows(self):
        # A line with no name but an mpn (or ГОСТ/чертёж) is identifiable — keep it.
        result = _normalize_items([{"name": "", "mpn": "ABC-123"}], VALID_CODES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mpn"], "ABC-123")
        self.assertEqual(result[0]["name"], "")

    def test_quantity_coercion(self):
        cases = [
            ({"name": "x", "quantity": "5"}, 5),
            ({"name": "x", "quantity": 3.9}, 3),
            ({"name": "x", "quantity": 0}, 1),
            ({"name": "x", "quantity": -4}, 1),
            ({"name": "x", "quantity": "не число"}, 1),
            ({"name": "x"}, 1),
            ({"name": "x", "quantity": None}, 1),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_normalize_items([raw], VALID_CODES)[0]["quantity"], expected)

    def test_unit_code_validated_against_reference(self):
        valid = _normalize_items([{"name": "x", "unit_code": "pce"}], VALID_CODES)
        self.assertEqual(valid[0]["unit_code"], "PCE")  # upper-cased and accepted
        off_list = _normalize_items([{"name": "x", "unit_code": "ZZZ"}], VALID_CODES)
        self.assertEqual(off_list[0]["unit_code"], "")  # discarded

    def test_field_length_truncation(self):
        raw = {
            "name": "n" * 50,
            "mpn": "m" * 200,
            "gost_drawing": "g" * 200,
            "unit": "u" * 50,
        }
        result = _normalize_items([raw], VALID_CODES)[0]
        self.assertEqual(len(result["mpn"]), 120)
        self.assertEqual(len(result["gost_drawing"]), 120)
        self.assertEqual(len(result["unit"]), 32)
        # name/note are TextFields — not truncated here.
        self.assertEqual(len(result["name"]), 50)

    def test_strips_whitespace(self):
        result = _normalize_items([{"name": "  Болт  ", "note": "  прим  "}], VALID_CODES)[0]
        self.assertEqual(result["name"], "Болт")
        self.assertEqual(result["note"], "прим")


@pytest.mark.django_db
def test_happy_path_returns_items(fake_gateway, no_units):
    fake_gateway.reply_json({"items": [{"name": "Болт", "quantity": 2}]})
    items = extract_request_items(b"Bolt,2\n", "req.csv")
    assert [(row["name"], row["quantity"]) for row in items] == [("Болт", 2)]
    body = fake_gateway.last_body
    assert body["model"] == "intake-model"
    assert body["metadata"]["tags"] == ["system=erp", "feature=intake", "model=intake-model"]
    assert body["response_format"]["type"] == "json_schema"
    # Данные клиента — в сообщении user, системный промпт — из файла без незаполненных плейсхолдеров.
    assert "Bolt,2" in fake_gateway.user_text()
    assert "Bolt,2" not in body["messages"][0]["content"]
    assert "{{" not in body["messages"][0]["content"]


@pytest.mark.django_db
def test_refusal_yields_empty(fake_gateway, no_units):
    fake_gateway.reply_refusal()
    assert extract_request_items(b"x\n", "req.csv") == []


@pytest.mark.django_db
def test_truncated_unparseable_json_yields_empty(fake_gateway, no_units):
    # Вывод оборван посреди JSON — не падаем, кусок просто пустой.
    fake_gateway.reply_text('{"items": [{"name": "Бол', finish_reason="length")
    assert extract_request_items(b"x\n", "req.csv") == []


@pytest.mark.django_db
def test_every_chunk_failing_raises_for_parser_fallback(fake_gateway, no_units, settings):
    settings.AI_IMPORT_CHUNK_ROWS = 1
    fake_gateway.reply_http_error(502).reply_transport_error()
    with pytest.raises(RuntimeError, match="AI_EXTRACT_ALL_CHUNKS_FAILED"):
        extract_request_items(b"head\nrow1\nrow2\n", "req.csv")


@pytest.mark.django_db
def test_one_failing_chunk_keeps_the_others(fake_gateway, no_units, settings):
    settings.AI_IMPORT_CHUNK_ROWS = 1
    fake_gateway.reply_http_error(502).reply_json({"items": [{"name": "Шайба"}]})
    items = extract_request_items(b"head\nrow1\nrow2\n", "req.csv")
    assert [row["name"] for row in items] == ["Шайба"]


@pytest.mark.django_db
def test_bulk_import_retries_transient_gateway_errors(fake_gateway, no_units, settings, monkeypatch):
    """Пакетный импорт (Celery) повторяет сеть/5xx шлюза AI_MAX_RETRIES раз; 4xx — не повторяет."""
    monkeypatch.setattr("ai.services.gateway.time.sleep", lambda seconds: None)
    settings.AI_MAX_RETRIES = 2
    fake_gateway.reply_transport_error().reply_http_error(503).reply_json({"items": [{"name": "Гайка"}]})
    items = extract_request_items(b"x\n", "req.csv")
    assert [row["name"] for row in items] == ["Гайка"]
    assert fake_gateway.calls == 3


@pytest.mark.django_db
def test_vision_file_goes_as_a_block_and_is_masked(fake_gateway, no_units):
    fake_gateway.reply_json({"items": []})
    extract_request_items(b"\x89PNG fake", "scan.png")
    body = fake_gateway.last_body
    first = body["messages"][1]["content"][0]
    assert first["type"] == "image_url"
    assert first["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["metadata"]["mask_input"] is True


@pytest.mark.django_db
def test_vision_gateway_down_raises_code(fake_gateway, no_units):
    fake_gateway.reply_transport_error()
    with pytest.raises(RuntimeError, match="AI_GATEWAY_UNAVAILABLE"):
        extract_request_items(b"%PDF-1.4", "doc.pdf")


def test_disabled_raises(settings):
    settings.AI_IMPORT_ENABLED = False
    with pytest.raises(RuntimeError, match="AI_IMPORT_DISABLED"):
        extract_request_items(b"x", "req.csv")
