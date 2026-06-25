"""M8 + M9 regression: the AI заявка-import must NOT discard the clean
`name_canonical` the model paid to produce.

M8 — the buyer's grid (imported_raw_name) must show the CLEAN canonical name when
     the AI gave us one, not the dirty raw string. The verbatim original is kept as
     provenance in `note` so nothing is silently lost.
M9 — QuoteItem.name_canonical must be persisted so bilingual catalog matching works.

The deterministic parser passes name_canonical='' → both display and name_canonical
fall back to the raw name (legacy behaviour, no regression).
"""

from django.test import TestCase

from accounts.models import Company, CustomUser
from crm.models import Deal, Quote
from sourcing.tasks import _build_quote_item


class BuildQuoteItemCanonicalTest(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Canon Co", inn="999000111")
        user = CustomUser.objects.create_user(
            username="canonbuyer", email="canonbuyer@test.com", password="password123"
        )
        deal = Deal.objects.create(company=company, client=user)
        self.quote = Quote.objects.create(deal=deal, version=1)

    def test_ai_canonical_becomes_display_and_search_key(self):
        """M8: clean canonical is the displayed name; M9: persisted as name_canonical.
        Raw original is kept as provenance in note."""
        item = _build_quote_item(
            self.quote,
            name="tormoznaya koloda",
            quantity=3,
            unit="шт",
            note="срочно",
            name_canonical="Тормозная колодка",
        )

        # M8 — buyer's grid shows the CLEAN name, not the dirty transliteration.
        self.assertEqual(item.imported_raw_name, "Тормозная колодка")
        # M9 — canonical persisted as the кириллический catalog-search key.
        self.assertEqual(item.name_canonical, "Тормозная колодка")
        # Provenance: the verbatim original survives in the note, plus the client's own.
        self.assertIn("срочно", item.note)
        self.assertIn("tormoznaya koloda", item.note)

    def test_canonical_equal_to_raw_adds_no_provenance(self):
        """When canonical == raw, don't pollute the note with a redundant copy."""
        item = _build_quote_item(
            self.quote,
            name="Автосцепка СА-3",
            quantity=1,
            name_canonical="Автосцепка СА-3",
        )
        self.assertEqual(item.imported_raw_name, "Автосцепка СА-3")
        self.assertEqual(item.name_canonical, "Автосцепка СА-3")
        self.assertNotIn("Исходное наименование", item.note)

    def test_deterministic_parser_passes_blank_canonical(self):
        """Parser path (no name_canonical): display = raw, name_canonical stays empty,
        note untouched — legacy behaviour preserved."""
        item = _build_quote_item(
            self.quote,
            name="Краска ПФ-115 20кг",
            quantity=2,
            note="ссылка",
        )
        self.assertEqual(item.imported_raw_name, "Краска ПФ-115 20кг")
        self.assertEqual(item.name_canonical, "")
        self.assertEqual(item.note, "ссылка")
        self.assertNotIn("Исходное наименование", item.note)

    def test_canonical_truncated_to_column_limit(self):
        """name_canonical and imported_raw_name are CharField(500) — never overflow."""
        long_canonical = "Деталь " + "Я" * 600
        item = _build_quote_item(
            self.quote,
            name="raw",
            quantity=1,
            name_canonical=long_canonical,
        )
        self.assertEqual(len(item.name_canonical), 500)
        self.assertEqual(len(item.imported_raw_name), 500)
