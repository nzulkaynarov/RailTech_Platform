"""«Подогнать»: убирает почти пустую последнюю страницу, даёт воздух короткому письму, честно отказывает."""

from __future__ import annotations

from typing import Any

import pytest

from rt_docs.contracts import validate_body
from rt_docs.errors import RenderTimeoutError
from rt_docs.fit import apply_tuning, fit
from rt_docs.model import Density, Layout
from rt_docs.pdf import Prepared, prepare, render_pdf
from tests import samples


def prepared(body: dict[str, Any], layout: Layout = Layout.LETTER) -> Prepared:
    return prepare(body, letterhead=samples.LETTERHEAD, layout=layout, meta=samples.LETTER_META, values=samples.VALUES)


def test_letter_of_1_2_pages_fits_on_one_page_and_the_result_is_saved_in_the_body() -> None:
    body = samples.letter_paragraphs(8)
    result = fit(prepared(body))
    assert result.before.pages == 2 and result.before.last_page_fill < 0.2
    assert result.result.stats.pages == 1
    assert result.actions[0].code == "density" and "«Обычно» → «Компактно»" in result.actions[0].message
    assert result.passes == 2  # исходник + один кандидат; итог в одну страницу — без прохода с номерами
    assert result.tuning.density is Density.COMPACT
    # сохранённая подгонка: тот же рендер без повторного «Подогнать» — предпросмотр и выпуск совпадают
    tuned = apply_tuning(body, result.tuning)
    validate_body(tuned)
    assert tuned["page"]["density"] == "compact"
    again = render_pdf(
        tuned, letterhead=samples.LETTERHEAD, layout=Layout.LETTER, meta=samples.LETTER_META, values=samples.VALUES
    )
    assert again.stats == result.result.stats


def test_meaningful_two_pages_are_left_as_is() -> None:
    result = fit(prepared(samples.letter_paragraphs(11)))
    assert result.result.stats.pages == 2 and result.before.last_page_fill > 0.2
    assert [a.code for a in result.actions] == ["none"]
    assert result.passes == 2  # исходник + проход с «Стр. N из M»; кандидатов нет


def test_short_letter_gets_air_and_stays_on_one_page() -> None:
    body = samples.body(
        [samples.para("Уважаемый коллега!"), samples.para(samples.SENTENCES[0]), samples.signature(samples.DIRECTOR)]
    )
    result = fit(prepared(body))
    assert result.before.pages == 1 and result.before.last_page_fill < 0.4
    assert result.result.stats.pages == 1
    assert result.result.stats.last_page_fill > result.before.last_page_fill
    assert {a.code for a in result.actions} == {"density", "lead"}
    assert result.passes == 2
    tuned = apply_tuning(body, result.tuning)
    validate_body(tuned)
    assert tuned["page"]["density"] == "spacious" and tuned["page"]["tuning"]["leadMm"] in (10, 20)


def test_forced_page_break_cannot_be_fitted_and_says_why() -> None:
    body = samples.letter_short()
    body["doc"]["content"][-2:-2] = [{"type": "pageBreak"}]
    result = fit(prepared(body))
    assert result.result.stats.pages == 2
    assert [a.code for a in result.actions] == ["kept"]
    assert "не убрать" in result.actions[0].message
    assert result.passes == 5  # исходник + три кандидата (не больше) + проход с номерами страниц


def test_timeout_is_a_clear_error() -> None:
    body = samples.body(samples.items_table(300))
    with pytest.raises(RenderTimeoutError, match="timeout"):
        fit(prepared(body, Layout.COMMERCIAL), timeout_s=0.05)
