"""Тесты отметки основания подписи и блока проверки с QR-кодом (SIGN-3, ADR-0024 п. 5)."""

from __future__ import annotations

from datetime import date
from typing import Any

from rt_docs.model import DocumentMeta, Layout
from rt_docs.prepare import document_html, prepare
from tests import samples


def render(body: dict[str, Any], *, draft: bool, meta: DocumentMeta) -> str:
    prepared = prepare(body, letterhead=samples.LETTERHEAD, layout=Layout.LETTER, meta=meta, draft=draft)
    return document_html(prepared, page_numbers=False)


def test_basis_text_in_signature() -> None:
    body = samples.body(
        [
            samples.para("Просим согласовать график поставок."),
            samples.signature({"role": "Коммерческий директор", "name": "Рахимов А. Т."}),
        ]
    )
    meta = DocumentMeta(
        number="ИСХ-042/26",
        date=date(2026, 11, 5),
        basis_text="Действует по доверенности № Д-14/26 от 15.01.2026 (до 31.12.2026)",
    )
    out = render(body, draft=False, meta=meta)
    assert '<div class="rt-sign-basis">Действует по доверенности № Д-14/26 от 15.01.2026 (до 31.12.2026)</div>' in out
    assert "Коммерческий директор" in out
    assert "Рахимов А. Т." in out


def test_verification_code_and_qr_in_final() -> None:
    body = samples.body(
        [
            samples.para("Официальный ответ на обращение."),
            samples.signature({"role": "Директор", "name": "Иванов И. И."}),
        ]
    )
    code = "V7K9Q2P4M1"
    url = f"https://cabinet.railtech.uz/v/{code}"
    meta = DocumentMeta(
        number="ИСХ-100/26",
        date=date(2026, 11, 5),
        verification_code=code,
        verification_url=url,
    )
    out = render(body, draft=False, meta=meta)
    assert '<div class="rt-verify-code-inline">' in out
    assert code in out
    assert '<div class="rt-verify-block">' in out
    assert '<div class="rt-verify-qr">' in out
    assert "<svg" in out
    assert url in out
    assert "rt-running-docref" in out
    assert f"ИСХ-100/26 · Код проверки: {code}" in out


def test_verification_code_suppressed_in_draft() -> None:
    body = samples.body(
        [
            samples.para("Проект письма."),
            samples.signature({"role": "Директор"}),
        ]
    )
    code = "V7K9Q2P4M1"
    url = f"https://cabinet.railtech.uz/v/{code}"
    meta = DocumentMeta(
        number="ИСХ-100/26",
        date=date(2026, 11, 5),
        verification_code=code,
        verification_url=url,
    )
    out = render(body, draft=True, meta=meta)
    assert code not in out
    assert url not in out
    assert '<div class="rt-verify-block">' not in out
    assert '<div class="rt-verify-code-inline">' not in out
    assert '<div class="rt-draft-mark">' in out
