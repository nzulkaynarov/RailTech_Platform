"""Письмо и служебная записка по сетке документа (ДОК-5, стандарт §4–§5): инфоблок вместо паспорта письма, окно
адресата, подвал и «Стр. N из M» на каждой странице, подпись одной строкой с отметкой подписания и QR."""

from __future__ import annotations

from dataclasses import replace

import pytest

from rt_docs.model import Layout, RenderResult
from rt_docs.pdf import render_pdf
from tests import samples
from tests.pdf.pdfcheck import fonts, pages


def font_warnings(result: RenderResult) -> list[str]:
    return [w for w in result.warnings if "missing from the document font" in w]


OLD_PASSPORT = ("№ ИСХ-015/26 от", "На № 12")


def letter(paragraphs: int, meta=samples.GRID_LETTER_META) -> RenderResult:  # type: ignore[no-untyped-def]
    return render_pdf(
        samples.letter_paragraphs(paragraphs),
        letterhead=samples.GRID_LETTERHEAD,
        layout=Layout.LETTER,
        meta=meta,
        highlight_missing=False,
    )


@pytest.fixture(scope="module")
def one_page() -> RenderResult:
    return letter(3)


@pytest.fixture(scope="module")
def three_pages() -> RenderResult:
    return letter(22)


def test_one_page_letter_has_the_info_block_window_and_footer(one_page: RenderResult) -> None:
    assert one_page.stats.pages == 1 and not font_warnings(one_page)
    text = pages(one_page.pdf)[0].text
    for label in ("Письмо", "Исх. №", "Дата", "На ваш №", "Исполнитель", "Почта", "Код проверки"):
        assert label in text, label
    assert "ООО «Тест» · ул. Садыка Азимова, 47/33 · 100000 Ташкент" in text, "строка обратного адреса над окном"
    assert "АО «Пример Логистик»" in text and "Руководство" in text and "Код НДС 3260 1000 0001" in text
    assert "Стр." not in text, "на одной странице номера страниц нет"
    assert not any(old in text for old in OLD_PASSPORT), "паспорта письма больше нет"


def test_three_page_letter_pages_footer_and_running_head() -> None:
    result = letter(22)
    assert result.stats.pages == 3
    first, second, third = (page.text for page in pages(result.pdf))
    for number, text in enumerate((first, second, third), start=1):
        assert f"Стр. {number} из 3" in text
        assert "Руководство" in text and "Код НДС 3260 1000 0001" in text, f"подвал на странице {number}"
    assert "Исполнитель" in first and "Исполнитель" not in second, "полный инфоблок — только на первой странице"
    assert "Исх. №" in second and "ИСХ-015/26" in second and "Дата" in second, "мини-инфоблок со 2-й страницы"
    assert "Письмо" not in second


def test_signature_line_has_signing_fact_and_verification(one_page: RenderResult) -> None:
    text = pages(one_page.pdf)[-1].text
    assert "Подписано электронной подписью" in text and "23.11.2026 10:15" in text
    assert text.count("AB12CD34") == 2, "код проверки: в инфоблоке и под QR"
    assert "Проверка подлинности документа" not in text, "отдельного блока проверки нет — QR в строке подписи"


def test_draft_has_no_number_no_signing_fact_no_qr() -> None:
    result = render_pdf(
        samples.letter_paragraphs(3),
        letterhead=samples.GRID_LETTERHEAD,
        layout=Layout.LETTER,
        meta=samples.GRID_LETTER_META,
        draft=True,
        highlight_missing=False,
    )
    text = pages(result.pdf)[0].text
    assert "ПРОЕКТ" in text and "без номера" in text and "ИСХ-015/26" not in text
    assert "Подписано электронной подписью" not in text and "AB12CD34" not in text


def test_uzbek_labels_use_the_owner_alphabet() -> None:
    from rt_docs.labels import GRID_LABELS

    meta = replace(
        samples.GRID_LETTER_META,
        kind_label=GRID_LABELS["kind_letter"]["uz"],
        info=(
            replace(samples.GRID_LETTER_META.info[0], label=GRID_LABELS["number_out"]["uz"]),
            replace(samples.GRID_LETTER_META.info[1], label=GRID_LABELS["date"]["uz"]),
            replace(samples.GRID_LETTER_META.info[3], label=GRID_LABELS["executor"]["uz"]),
            replace(samples.GRID_LETTER_META.info[4], label=GRID_LABELS["email"]["uz"]),
        ),
    )
    result = render_pdf(
        samples.letter_uz(),
        letterhead=samples.GRID_LETTERHEAD,
        layout=Layout.LETTER,
        meta=meta,
        highlight_missing=False,
    )
    assert not font_warnings(result), "ç ş ö ğ есть в шрифте документа"
    text = pages(result.pdf)[0].text
    assert "Çiqiş №" in text and "Ijroçi" in text and "Poçta" in text


def test_memo_has_no_company_footer_and_a_closing_line() -> None:
    meta = replace(
        samples.GRID_LETTER_META,
        kind_label="Служебная записка",
        addressee=(),
        info=samples.GRID_LETTER_META.info[:2],
        executor=None,
    )
    result = render_pdf(
        samples.letter_paragraphs(2),
        letterhead=samples.GRID_LETTERHEAD,
        layout=Layout.INTERNAL,
        meta=meta,
        highlight_missing=False,
    )
    text = pages(result.pdf)[0].text
    assert "Служебная записка" in text and "Исх. №" in text
    assert "Внутренний документ · Код проверки AB12CD34" in text
    assert "Руководство" not in text and "Код НДС" not in text


def test_only_package_fonts(one_page: RenderResult) -> None:
    used = fonts(one_page.pdf)
    assert used and all("RT-Doc" in name for name in used), used
