"""Unit tests for the deterministic Excel header/column detector (no DB, no API).

Covers the regression where the parser ignored an «Артикул» column, so xlsx
imports always produced QuoteItems with an empty mpn even when the source file
carried the article code (the AI path forwarded it, the parser path did not).
"""

import pandas as pd
from django.test import SimpleTestCase

from sourcing.tasks import detect_header_and_columns


class DetectColumnsTest(SimpleTestCase):
    def _detect(self, rows):
        return detect_header_and_columns(pd.DataFrame(rows))

    def test_detects_article_column(self):
        header_idx, cols = self._detect(
            [
                ["Наименование", "Артикул", "Кол-во", "Ед.изм", "Примечание"],
                ["Болт М12", "ГОСТ-7798", "10", "шт", "оцинкованный"],
            ]
        )
        self.assertEqual(header_idx, 0)
        self.assertEqual(cols["article"], 1)
        # Article must not steal the name column, and each logical column is distinct.
        self.assertEqual(cols["name"], 0)
        self.assertNotEqual(cols["article"], cols["name"])

    def test_article_synonyms(self):
        for header in ("Каталожный №", "MPN", "Part No", "Код производителя"):
            _, cols = self._detect([["Наименование", header, "Кол-во"], ["Болт", "X-1", "5"]])
            self.assertIsNotNone(cols, f"header row not found for {header!r}")
            self.assertEqual(cols["article"], 1, f"article not detected for {header!r}")

    def test_article_absent_is_none(self):
        _, cols = self._detect([["Наименование", "Кол-во", "Ед.изм"], ["Болт", "10", "шт"]])
        self.assertIsNone(cols["article"])
        # The other columns still resolve as before.
        self.assertEqual(cols["name"], 0)
        self.assertEqual(cols["qty"], 1)
