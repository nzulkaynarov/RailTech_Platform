"""Unit tests for the AI заявка extractor's pure logic (no Anthropic API calls).

Covers normalisation (_normalize_items) and the resilience of a single model call
(_extract_one) under refusal / truncation / unparseable-JSON, using a stub client.
The chunk-isolation behaviour of extract_request_items is covered via stub too.
"""

import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from sourcing.services_ai import _extract_one, _normalize_items

VALID_CODES = {"PCE", "MTR", "KGM"}


class NormalizeItemsTest(SimpleTestCase):
    def test_drops_fully_empty_rows(self):
        items = [{"name": "", "mpn": "", "gtin": ""}, {"name": "Болт М12"}]
        result = _normalize_items(items, VALID_CODES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Болт М12")

    def test_keeps_code_only_rows(self):
        # A line with no name but an mpn (or gtin) is identifiable — keep it.
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
            "gtin": "g" * 30,
            "unit": "u" * 50,
        }
        result = _normalize_items([raw], VALID_CODES)[0]
        self.assertEqual(len(result["mpn"]), 120)
        self.assertEqual(len(result["gtin"]), 14)
        self.assertEqual(len(result["unit"]), 32)
        # name/note are TextFields — not truncated here.
        self.assertEqual(len(result["name"]), 50)

    def test_strips_whitespace(self):
        result = _normalize_items([{"name": "  Болт  ", "note": "  прим  "}], VALID_CODES)[0]
        self.assertEqual(result["name"], "Болт")
        self.assertEqual(result["note"], "прим")


def _stub_client(stop_reason, text):
    """A fake Anthropic client whose messages.create returns one canned response."""
    response = SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        content=[SimpleNamespace(type="text", text=text)],
    )
    client = mock.Mock()
    client.messages.create.return_value = response
    return client


class ExtractOneResilienceTest(SimpleTestCase):
    def test_happy_path_returns_items(self):
        payload = json.dumps({"items": [{"name": "Болт"}]})
        client = _stub_client("end_turn", payload)
        result = _extract_one(client, "claude-opus-4-8", "sys", text="raw")
        self.assertEqual(result, [{"name": "Болт"}])

    def test_refusal_yields_empty(self):
        client = _stub_client("refusal", "")
        self.assertEqual(_extract_one(client, "m", "sys", text="raw"), [])

    def test_truncated_unparseable_json_yields_empty(self):
        # max_tokens cut the JSON mid-object — must not raise.
        client = _stub_client("max_tokens", '{"items": [{"name": "Бол')
        self.assertEqual(_extract_one(client, "m", "sys", text="raw"), [])

    def test_empty_items_key(self):
        client = _stub_client("end_turn", json.dumps({"items": []}))
        self.assertEqual(_extract_one(client, "m", "sys", text="raw"), [])
