"""Белый список ресурсов рендера и вшитые шрифты (OFL, глифы узбекской латиницы и кириллицы)."""

from __future__ import annotations

import base64
from importlib import resources

import pytest

from rt_docs.fetcher import FONT_NAMES, ResourcePolicy
from rt_docs.fonts import REQUIRED_CHARS, coverage, missing_glyphs
from rt_docs.model import Logo
from tests import samples

PNG = samples.png(4, 4)


def test_allows_only_embedded_fonts_logo_and_raster_data() -> None:
    policy = ResourcePolicy(logo=Logo(PNG, "image/png"))
    font = policy.resolve("rtdocs:fonts/NotoSans-Regular.ttf")
    assert font is not None and font.mime == "font/ttf" and font.data[:4] == b"\x00\x01\x00\x00"
    logo = policy.resolve("rtdocs:logo")
    assert logo is not None and logo.data == PNG
    data = policy.resolve("data:image/png;base64," + base64.b64encode(PNG).decode())
    assert data is not None and data.data == PNG
    assert policy.blocked == []


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
        "https://example.org/logo.png",
        "ftp://example.org/x",
        "rtdocs:fonts/../../pyproject.toml",
        "rtdocs:fonts/OFL.txt",
        "rtdocs:logo",  # логотипа в бланке нет
        "data:image/svg+xml;base64,PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+",
        "data:text/html,<script>alert(1)</script>",
        "/etc/passwd",
    ],
)
def test_everything_else_is_blocked_and_recorded(url: str) -> None:
    policy = ResourcePolicy()
    assert policy.resolve(url) is None
    assert policy.blocked == [url]


@pytest.mark.parametrize("family", ["sans", "serif"])
def test_fonts_cover_uzbek_latin_and_cyrillic(family: str) -> None:
    have = coverage(family)
    assert [c for c in REQUIRED_CHARS if ord(c) not in have] == []
    assert missing_glyphs(samples.UZ_TEXT + "Ташкент, № 15 — «ок» … 1 234,56 сум", family) == []


def test_missing_glyphs_reports_characters_outside_the_font() -> None:
    assert missing_glyphs("漢字 ok \U0001f600") == ["字", "漢", "\U0001f600"]


def test_font_files_ship_with_the_ofl_license() -> None:
    fonts = resources.files("rt_docs").joinpath("fonts")
    assert fonts.joinpath("OFL.txt").read_text(encoding="utf-8").find("SIL OPEN FONT LICENSE Version 1.1") > 0
    for name in FONT_NAMES:
        assert fonts.joinpath(name).is_file(), name
