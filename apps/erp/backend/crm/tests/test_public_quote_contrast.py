"""Публичная страница КП — клиентский экран: цвет текста держит контраст WCAG AA (≥ 4.5:1).

FIX-58, D-06: axe на странице КП (`.brand-meta`, подписи `.mk`, `.tk`, `.item-sub`) нашёл серый
`#7a828f` на белом — 3,87:1. Тест читает цвета текста из шаблона и считает контраст по формуле WCAG,
чтобы возврат «бледного» серого не прошёл молча. Работает без БД: шаблон — обычный файл.
"""

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "crm" / "quote_public_page.html"
WHITE = "#ffffff"


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(fg: str, bg: str = WHITE) -> float:
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@pytest.mark.parametrize("variable", ["ink", "ink-soft", "muted"])
def test_text_variables_keep_aa_contrast_on_white(variable):
    css = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(rf"--{variable}:\s*(#[0-9a-fA-F]{{6}})", css)
    assert match, f"в шаблоне нет переменной --{variable}"
    ratio = contrast(match.group(1))
    assert ratio >= 4.5, f"--{variable}: {match.group(1)} на белом даёт {ratio:.2f}:1, нужно ≥ 4.5"
