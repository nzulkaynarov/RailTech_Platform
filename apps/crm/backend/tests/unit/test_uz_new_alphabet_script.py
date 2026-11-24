# ruff: noqa: E501, PT018
"""Tests of scripts/uz_new_alphabet.py (the one-off converter of task uz1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[5] / "scripts"
if not (SCRIPTS / "uz_new_alphabet.py").exists():  # the CRM image has no repository scripts
    pytest.skip("scripts/uz_new_alphabet.py is not available", allow_module_level=True)
sys.path.insert(0, str(SCRIPTS))

from uz_new_alphabet import (  # type: ignore[import-not-found]  # noqa: E402
    convert_json,
    convert_po,
    convert_py,
    convert_ts,
    convert_uz,
)

# ── Digraphs and oʻ/gʻ ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # the repo's existing new-alphabet strings are the reference
        ("Chiqish", "Çiqiş"),
        ("yuboruvchi", "yuboruvçi"),
        ("Narx soʻrovi", "Narx sörovi"),
        ("toʻlov", "tölov"),
        ("Oʻzbekcha", "Özbekça"),
        ("ishtirokchilar", "iştirokçilar"),
        ("soʻm", "söm"),
        # capitals
        ("Shartnoma", "Şartnoma"),
        ("Oʻchirish", "Öçiriş"),
        ("Gʻalaba", "Ğalaba"),
        # loanwords: «sh»/«ch» are real digraphs here, the new alphabet writes ş/ç
        ("mashina", "maşina"),
        ("shtamp", "ştamp"),
        ("chek", "çek"),
        ("podshipnik", "podşipnik"),
        ("masshtab", "masştab"),
        ("seshanba", "seşanba"),
        ("Texnika", "Texnika"),
        ("Yetkazib berish", "Yetkazib beriş"),
        # word-final gʻ after a vowel
        ("togʻ", "toğ"),
        ("Mablag‘", "Mablağ"),
        ("qoʻngʻiroq", "qönğiroq"),
    ],
)
def test_words(old: str, new: str) -> None:
    assert convert_uz(old) == new


@pytest.mark.parametrize("apostrophe", ["ʻ", "‘", "’", "'", "`", "ʼ"])
def test_every_o_g_apostrophe_variant(apostrophe: str) -> None:
    assert convert_uz(f"bo{apostrophe}lim") == "bölim"
    assert convert_uz(f"bog{apostrophe}lanish") == "boğlaniş"
    assert convert_uz(f"O{apostrophe}zbek") == "Özbek"
    assert convert_uz(f"G{apostrophe}alaba") == "Ğalaba"


# ── Glottal stop ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("apostrophe", ["ʻ", "‘", "’", "'", "`", "ʼ"])
def test_glottal_stop_normalised(apostrophe: str) -> None:
    assert convert_uz(f"ma{apostrophe}lumot") == "maʼlumot"
    assert convert_uz(f"Ta{apostrophe}minotchi") == "Taʼminotçi"
    assert convert_uz(f"e{apostrophe}lon") == "eʼlon"
    assert convert_uz(f"Mas{apostrophe}ul") == "Masʼul"
    assert convert_uz(f"Noma{apostrophe}lum") == "Nomaʼlum"


def test_glottal_stop_word_final_and_s_h_boundary() -> None:
    assert convert_uz("man' etilgan") == "manʼ etilgan"
    assert convert_uz("Isʼhoq") == "Isʼhoq"  # ʼ separates s and h: no ş
    assert convert_uz("Is'hoq") == "Isʼhoq"


def test_suffix_separator_after_foreign_word_is_left_alone() -> None:
    # not a glottal stop: an Uzbek suffix glued to a foreign name — a human decides
    assert convert_uz("Disk'da") == "Disk'da"
    assert convert_uz("Drive'ni") == "Drive'ni"
    assert convert_uz("ERP'ni ulang") == "ERP'ni ulang"


def test_quotes_are_not_apostrophes() -> None:
    assert convert_uz("'Saqlash' tugmasini bosing") == "'Saqlaş' tugmasini bosing"
    assert convert_uz("‘Shablon’ — bo‘lim") == "‘Şablon’ — bölim"


# ── Never touched ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "{{shown}}",
        "{{channel}}",
        "{name}",
        "{0}",
        "%(company)s",
        "${chatId}",
        "$t(common.shablon)",
        '<a href="https://cabinet.railtech.uz/shablon" class="sh">',
        "<strong>",
        "&nbsp;",
        "https://example.uz/chiqish?shablon=1",
        "www.shop.uz",
        "shoh.chorshanba@example.uz",
        "shartnoma.pdf",
        "(.xlsx)",
        "`kod_shablon`",
        "can_act",
        "chatId",
        "gemini-3.8-flash",
        "SHA-256",
        "CRM",
        "ERP",
        "INN/STIR",
        "MFO",
        "QQS",
        "AQSH",
        "CHIQ",
        "MChJ",
        "JShShIR",
        "HSH-2026/01",
        "/start",
        "/human",
        "Telegram",
        "Siemens",
        "Didox",
        "Excel",
        "PDF",
        "Shopify",
        "Chrome",
        "ChatGPT",
        "RailTech",
        "English",
        "Shift+Enter",
    ],
)
def test_protected(text: str) -> None:
    assert convert_uz(text) == text


def test_protected_inside_sentence() -> None:
    src = "{{name}}, <strong>«{{company}}»</strong> shartnomasi Telegramda: https://t.me/shop_bot — %(sum)s soʻm"
    assert convert_uz(src) == (
        "{{name}}, <strong>«{{company}}»</strong> şartnomasi Telegramda: https://t.me/shop_bot — %(sum)s söm"
    )


def test_brand_suffix_still_converted() -> None:
    assert convert_uz("Telegramga ulash") == "Telegramga ulaş"
    assert convert_uz("TTni oching") == "TTni oçing"


# ── Idempotence ────────────────────────────────────────────────────────────────────────────────────

SAMPLES = [
    "Soʻrovingizni qabul qildik va tez orada siz bilan bogʻlanamiz.",
    "Ma'lumotlar yo'qolmagan: qayta urinib ko'ring.",
    "Bot sozlamalari administratorga va direktorga (faqat ko‘rish) ochiq.",
    "Disk'ga WebDAV orqali kirish, masalan «RailTech zaxira».",
    "Hozircha hech narsa eʼlon qilinmagan — kabinet ochiq.",
    "{{total}} sahifadan {{shown}} tasi ko'rsatilgan.",
    "Tab va Shift Tab",
    "F.I.Sh. va lavozimi",
]


@pytest.mark.parametrize("text", SAMPLES)
def test_idempotent(text: str) -> None:
    once = convert_uz(text)
    assert convert_uz(once) == once


def test_already_new_alphabet_is_unchanged() -> None:
    new = "Masʼulga şu bölimlar kerak; tekşiriş faqat ogohlantiradi. Özbekça, söm, tölov, Çiqiş."
    assert convert_uz(new) == new


# ── File handlers ──────────────────────────────────────────────────────────────────────────────────


def test_json_touches_values_only_and_keeps_formatting() -> None:
    src = '{\n  "shablon": "Shablon",\n  "chiqish": {\n    "label": "Chiqish {{count}}"\n  },\n  "list": ["bo‘sh"]\n}\n'
    res = convert_json(src, "x.json")
    assert res.text == (
        '{\n  "shablon": "Şablon",\n  "chiqish": {\n    "label": "Çiqiş {{count}}"\n  },\n  "list": ["böş"]\n}\n'
    )
    assert json.loads(res.text)["shablon"] == "Şablon"
    assert len(res.changes) == 3


def test_json_escapes_preserved() -> None:
    src = '{"a": "Shu \\"bo‘lim\\"\\nchiqish"}'
    res = convert_json(src)
    assert res.text == '{"a": "Şu \\"bölim\\"\\nçiqiş"}'


def test_po_msgstr_only() -> None:
    src = (
        'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
        'msgid "Shablon %(name)s"\nmsgstr "Shablon %(name)s"\n\n'
        'msgid "Long"\nmsgstr ""\n"Shaxsiy kabinet "\n"<strong>oʻting</strong>"\n'
    )
    res = convert_po(src)
    assert 'msgid "Shablon %(name)s"' in res.text
    assert 'msgstr "Şablon %(name)s"' in res.text
    assert '"Şaxsiy kabinet "\n"<strong>öting</strong>"' in res.text
    assert '"Content-Type: text/plain; charset=UTF-8\\n"' in res.text
    assert len(res.changes) == 3


def test_ts_uz_properties_only() -> None:
    src = (
        "  title: {\n    ru: 'Shablon',\n    uz: 'Shablon (can_act)',\n    en: 'Push channel',\n  },\n"
        "  content: {\n    uz: [\n      'Bo‘lim',\n      \"O'chirish\",\n    ],\n  },\n"
        "  lang: 'ru' | 'uz' | 'en';\n  uz: string;\n"
    )
    res = convert_ts(src)
    assert "ru: 'Shablon'" in res.text
    assert "uz: 'Şablon (can_act)'" in res.text
    assert "en: 'Push channel'" in res.text
    assert "'Bölim'" in res.text and '"Öçiriş"' in res.text
    assert "uz: string;" in res.text
    assert len(res.changes) == 3


def test_py_uz_values_only() -> None:
    src = """
LABELS = {"ru": "Шаблон", "uz": "Shablon", "en": "Shablon"}
NESTED = {"shablon": {"uz": ("dushanba", "chorshanba")}}
def f(clean, name):
    return {"uz": f"Assalomu, {clean.chop('sh')}! Ochish{'' if name else 'sh'}" if clean else "Shu yerda"}
TEXT = _t("Шаблон", "Shablon {company}", "Shablon")
ERR = _fail("rule_sh", "Шаблон", "bo‘lim", "Shablon")
OBJ = LocalizedText(ru="x", uz="Ochish", en="Ochish")
"""
    res = convert_py(src, "x.py")
    out = res.text
    assert '"en": "Shablon"' in out and '"uz": "Şablon"' in out
    assert '"shablon": {"uz": ("duşanba", "çorşanba")}' in out
    assert "{clean.chop('sh')}" in out and "{'' if name else 'sh'}" in out
    assert "f\"Assalomu, {clean.chop('sh')}! Oçiş" in out
    assert 'else "Şu yerda"' in out
    assert '_t("Шаблон", "Şablon {company}", "Shablon")' in out
    assert '_fail("rule_sh", "Шаблон", "bölim", "Shablon")' in out
    assert 'uz="Oçiş", en="Ochish"' in out


def test_py_excluded_files() -> None:
    src = '_SWITCH = {"uz": ("o\'zbekcha",)}\n'
    res = convert_py(src, "app/domain/language.py")
    assert res.text == src and res.skipped


def test_company_name_next_to_legal_form_is_kept() -> None:
    assert (
        convert_uz("Buyurtmachi sifatida (MChJ «Toshkent Logistik»)")
        == "Buyurtmaçi sifatida (MChJ «Toshkent Logistik»)"
    )
    assert convert_uz("«Chorsu Savdo» MChJ bilan shartnoma") == "«Chorsu Savdo» MChJ bilan şartnoma"
    assert convert_uz("«Saqlash» tugmasini bosing") == "«Saqlaş» tugmasini bosing"


@pytest.mark.parametrize("code", ["OʻRQ-547-son", "PQ-123", "OʻzDSt 1234", "O'z DSt"])
def test_legal_act_and_standard_codes_kept(code: str) -> None:
    assert convert_uz(code) == code
