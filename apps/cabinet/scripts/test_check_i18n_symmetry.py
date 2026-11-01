"""Тест правила «defaultValue в t() запрещён» проверки словарей Cabinet (CAB-FIX-2, K7).

Запуск: make -C apps/cabinet i18n-check (или python3 -m unittest discover -s scripts -p 'test_*.py').
"""
import unittest

import check_i18n_symmetry as check


class DefaultValueBanTest(unittest.TestCase):
    def test_flags_default_value_in_t_call(self):
        text = "const a = t('nav.sectionMain', { defaultValue: 'Основное' });\n"
        self.assertEqual(check.find_default_values(text), [1])

    def test_flags_multiline_and_i18n_t(self):
        text = (
            "const a = 1;\n"
            "i18n.t(\n"
            "  'common.copyLink',\n"
            "  { defaultValue: 'Копировать ссылку' },\n"
            ");\n"
            "t(`pages.${x}`, { count: 2, defaultValue: 'x' });\n"
        )
        self.assertEqual(check.find_default_values(text), [2, 6])

    def test_plain_calls_pass(self):
        text = (
            "t('nav.sectionMain');\n"
            "t('pages.quotes.numberVersion', { number: q.number, version: q.version });\n"
            "items.sort((a, b) => a - b); split(','); format({ defaultValue: 1 });\n"
        )
        self.assertEqual(check.find_default_values(text), [])

    def test_current_sources_have_no_default_value(self):
        self.assertEqual(check.collect_default_values(), [])


if __name__ == '__main__':
    unittest.main()
