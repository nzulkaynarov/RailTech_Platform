"""Эталонные PDF (DoD D-DOC1, исследование шаблонов §5): число страниц, заполненность последней, текст ru и uz.

Набор: письмо 5 строк, письмо ≈ 1,2 страницы (и «Подогнать»), договор на 3 страницы, счёт на 40 позиций, альбомная
спецификация. Заполненность проверяется двумя путями — статистикой WeasyPrint (rt_docs) и по PDF (pypdf).
"""

from __future__ import annotations

from typing import Any

import pytest

from rt_docs.model import DocumentMeta, Layout, RenderResult
from rt_docs.pdf import render_pdf
from tests import samples
from tests.pdf.pdfcheck import MM, fonts, pages, pdf_fill

WORDS = "Сто пятьдесят два миллиона триста сорок тысяч сум 00 тийин"
#: Эталоны из описания PR #295 и docs/architecture/rt-docs.md §6: точное число страниц, заполненность последней ±0,05.
EXPECTED = {
    "letter_short": (1, 0.47),
    "letter_uz": (1, 0.38),
    "letter_1_2": (2, 0.14),
    "letter_2": (2, 0.43),
    "contract": (3, 0.65),
    "invoice_40": (3, 0.23),
    "spec_landscape": (2, 0.68),
}
TOLERANCE = 0.05


def assert_reference(name: str, result: RenderResult) -> None:
    pages_expected, fill = EXPECTED[name]
    assert result.stats.pages == pages_expected, name
    assert abs(result.stats.last_page_fill - fill) <= TOLERANCE, (name, result.stats.last_page_fill)
    assert result.passes == (1 if pages_expected == 1 else 2), "второй проход — только для «Стр. N из M»"


def letter(body: dict[str, Any]) -> RenderResult:
    return render_pdf(
        body, letterhead=samples.LETTERHEAD, layout=Layout.LETTER, meta=samples.LETTER_META, values=samples.VALUES
    )


@pytest.fixture(scope="module")
def short_letter() -> RenderResult:
    return letter(samples.letter_short())


@pytest.fixture(scope="module")
def contract() -> RenderResult:
    return render_pdf(
        samples.contract(),
        letterhead=samples.LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(title="Договор поставки № Д-15/26", number="Д-15/26"),
        values=samples.VALUES,
        blocks={"doc.spec_table": samples.items_table(6), "doc.totals": samples.totals(WORDS)},
    )


@pytest.fixture(scope="module")
def invoice() -> RenderResult:
    return render_pdf(
        samples.invoice(),
        letterhead=samples.LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(title="Счёт на оплату № 47", number="СЧ-47/26"),
        values=samples.VALUES,
        blocks={
            "doc.items_table": samples.items_table(40),
            "doc.totals": samples.totals(WORDS),
            "doc.payment_requisites": samples.payment_requisites(),
        },
    )


@pytest.fixture(scope="module")
def specification() -> RenderResult:
    return render_pdf(
        samples.specification(),
        letterhead=samples.LETTERHEAD,
        layout=Layout.COMMERCIAL,
        meta=DocumentMeta(title="Спецификация (Приложение № 1)", number="Д-15/26"),
        values=samples.VALUES,
        blocks={"doc.spec_table": samples.items_table(20, landscape=True)},
    )


def assert_fill_matches_pdf(result: RenderResult, *, top_mm: float = 20, bottom_mm: float = 20) -> None:
    """Статистика WeasyPrint и измерение по PDF расходятся не больше чем на нижний вынос строки."""
    last = pages(result.pdf, bottom_margin_mm=bottom_mm)[-1]
    assert abs(pdf_fill(last, top_mm=top_mm, bottom_mm=bottom_mm) - result.stats.last_page_fill) < 0.03


def test_short_letter_is_one_page_without_page_numbers(short_letter: RenderResult) -> None:
    assert_reference("letter_short", short_letter)
    text = pages(short_letter.pdf)[0].text
    assert "Стр." not in text and " из 1" not in text
    assert "Уважаемый Бахтиёр Бахтиярович!" in text
    assert "Генеральному директору" in text and "№ ИСХ-015/26 от 28.10.2026" in text
    assert "Исп.: Исполнитель А. Б. Петрова" in text  # «Исполнитель» внизу последней страницы
    assert_fill_matches_pdf(short_letter)


def test_short_letter_uses_only_embedded_fonts(short_letter: RenderResult) -> None:
    used = fonts(short_letter.pdf)
    assert used and all("RT-Doc-Sans" in name for name in used), used


def test_uzbek_latin_and_cyrillic_letters_are_printed_and_extractable() -> None:
    result = render_pdf(
        samples.letter_uz(),
        letterhead=samples.LETTERHEAD,
        layout=Layout.LETTER,
        meta=DocumentMeta(number="CHQ-7/26", executor="Ijrochi: A. Petrova"),
        values={**samples.VALUES, "deal.number": "ZV-2026-104"},
    )
    assert_reference("letter_uz", result)
    assert not [w for w in result.warnings if "characters missing" in w]
    text = pages(result.pdf)[0].text
    for fragment in ("Oʻzbekiston", "gʻalla", "qoʻshimcha", "ўқғҳ", "ЎҚҒҲ", "boʻyicha", "M. Oʻ.", "imzo"):
        assert fragment in text, fragment


def test_long_letter_is_two_pages_with_page_numbers_and_running_number() -> None:
    result = letter(samples.letter_paragraphs(11))
    assert_reference("letter_2", result)
    first, second = pages(result.pdf)
    assert "Стр. 1 из 2" in first.text and "Стр. 2 из 2" in second.text
    assert "ИСХ-015/26" in second.text  # номер письма в колонтитуле со второй страницы
    assert "Исп.:" not in first.text and "Исп.:" in second.text
    assert_fill_matches_pdf(result)


def test_letter_of_1_2_pages_has_a_nearly_empty_last_page() -> None:
    result = letter(samples.letter_paragraphs(8))
    assert_reference("letter_1_2", result)
    assert result.stats.last_page_fill < 0.2  # почти пустая — её убирает «Подогнать» (test_fit)
    # подпись не одна: на второй странице вместе с предыдущим абзацем
    second = pages(result.pdf)[1].text
    assert "С уважением," in second and "подпись" in second


@pytest.mark.parametrize("extra", [3, 4, 5, 8])
def test_signature_never_goes_to_a_new_page_alone(extra: int) -> None:
    """Сдвигаем конец письма через границу страницы: подпись уходит только вместе с «С уважением,»."""
    body = samples.letter_paragraphs(6)
    for i in range(extra):
        body["doc"]["content"].insert(-2, samples.para(f"Дополнительная строка {i + 1}."))
    result = letter(body)
    sig_page = next(p for p in pages(result.pdf) if "подпись" in p.text)
    assert "С уважением," in sig_page.text


def test_contract_is_three_pages(contract: RenderResult) -> None:
    assert_reference("contract", contract)
    texts = [p.text for p in pages(contract.pdf)]
    assert "Стр. 3 из 3" in texts[2]
    assert all("Д-15/26" in t for t in texts[1:])
    assert "Поставщик" in texts[2] and "Покупатель" in texts[2] and texts[2].count("М. П.") == 2
    first = " ".join(texts[0].split())  # выключка по ширине: pypdf отдаёт двойные пробелы
    assert "ООО «Пример Логистик»" in first and "именуемое в дальнейшем «Покупатель»" in first
    assert_fill_matches_pdf(contract)


def test_invoice_40_items_repeats_header_and_keeps_totals_and_signature(invoice: RenderResult) -> None:
    result = pages(invoice.pdf)
    assert_reference("invoice_40", invoice)
    assert invoice.stats.pages == len(result)
    for page in result:
        if "Позиция" in page.text:
            assert "Наименование" in page.text and "Сумма" in page.text, "шапка таблицы на каждой странице"
    totals_page = next(p for p in result if "Итого к оплате" in p.text)
    assert "Позиция 40:" in totals_page.text, "итоги не отрываются от последней строки"
    signature_page = next(p for p in result if "подпись" in p.text)
    assert "Оплатить до" in signature_page.text, "подпись не одна на странице"
    assert "Позиция 1:" in result[0].text
    assert f"Стр. {len(result)} из {len(result)}" in result[-1].text
    assert_fill_matches_pdf(invoice)


def test_specification_is_landscape(specification: RenderResult) -> None:
    result = pages(specification.pdf, bottom_margin_mm=15)
    assert_reference("spec_landscape", specification)
    assert specification.stats.pages == len(result)
    assert all(p.width > p.height for p in result)
    assert abs(result[0].width - 297 * MM) < 1
    assert "Код ТН ВЭД" in result[1].text, "шапка повторяется"
    assert "Поставщик" in result[-1].text and "Покупатель" in result[-1].text
    assert_fill_matches_pdf(specification, top_mm=15, bottom_mm=15)


def test_render_report_lists_missing_values_and_no_blocked_urls(contract: RenderResult, invoice: RenderResult) -> None:
    for result in (contract, invoice):
        assert result.blocked_urls == ()
        assert not [w for w in result.warnings if not w.startswith("variable without value")]
