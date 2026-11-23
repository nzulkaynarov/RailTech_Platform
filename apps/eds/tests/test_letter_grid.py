"""Письмо по сетке документа (ДОК-5, стандарт документов §4–§5; pg).

Ввод рендера письма несёт вид и инфоблок «метка — значение» вместо паспорта письма, колонки подвала и строку обратного
адреса из бланка, факт подписания. Сам PDF (страницы, подвал на каждой, «Стр. N из M») проверяют эталонные тесты
`packages/rt-docs/tests/pdf/test_letter_grid_pdf.py`; здесь — что EDS кладёт в ввод и что из него получается в HTML
листа (без pango, тем же путём `prepare` → `document_html`, что и рендер).
"""

import copy
import re
from typing import Any

import httpx
import pytest
from rt_docs import Layout
from rt_docs.labels import EXECUTOR, GRID_LABELS, STAMP
from rt_docs.prepare import document_html, prepare

from app.container import Container
from app.models import Document
from app.services import render_process, renders
from tests.domain import Person
from tests.signing import sign_out
from tests.test_draft_pdf import draft_letter, make_ready
from tests.test_letterhead_letters import BODY, StubRenderer, deliver_letterhead, letter_json, run

pytestmark = pytest.mark.pg


@pytest.fixture
def deferred(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Хеши, которые API поставило бы в очередь после коммита."""
    found: list[str] = []

    async def record(self: Container, hashes: list[str]) -> None:
        found.extend(hashes)

    monkeypatch.setattr(Container, "defer_render", record)
    return found


OLD_PASSPORT = 'class="rt-letter-meta"'


def sheet(payload: dict[str, Any]) -> str:
    """HTML листа из ввода рендера — как в процессе пула, но без WeasyPrint."""
    letterhead, meta = render_process.render_inputs(payload, None, None)
    prepared = prepare(
        payload["body"],
        letterhead=letterhead,
        layout=Layout(payload["layout"]),
        meta=meta,
        highlight_missing=False,
        draft=bool(payload.get("draft")),
    )
    return document_html(prepared, page_numbers=True)


async def final_payload(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str], doc: str
) -> dict[str, Any]:
    assert (
        await client.post(f"/api/v1/documents/{doc}/registration-request", headers=staff["manager"].headers)
    ).status_code == 200
    assert (await sign_out(client, staff, doc)).status_code == 200
    stub = StubRenderer()
    assert await run(container, stub, deferred[-1]) == "ready"
    return stub.calls[0]


async def test_final_letter_has_info_block_window_footer_and_signing_fact(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    doc = await draft_letter(client, container, staff["manager"])
    payload = await final_payload(client, staff, container, deferred, doc)
    meta = payload["meta"]
    labels = [row["label"] for row in meta["info"]]
    assert meta["kind_label"] == "Письмо"
    assert labels[:2] == ["Исх. №", "Дата"], "первые две строки — мини-инфоблок со 2-й страницы"
    assert {"Исполнитель", "Почта", "Код проверки"} <= set(labels)
    number = next(row for row in meta["info"] if row["role"] == "number")
    assert number["value"] == meta["number"] and number["code"] is True
    assert meta["signed_text"] and payload["letterhead"]["return_address"]
    assert [c["title"] for c in payload["letterhead"]["footer_columns"]][:2] == ["ООО «RailTech»", "Руководство"]

    html = sheet(payload)
    assert 'class="rt-id"' in html and OLD_PASSPORT not in html, "инфоблок вместо паспорта письма"
    for label in ("Исх. №", "Исполнитель", "Почта", "Код проверки"):
        assert f'<th scope="row">{label}</th>' in html, label
    assert html.index("rt-id-window") < html.index("rt-info-box"), "окно адресата слева, инфоблок справа"
    assert '<div class="rt-id-addr rt-strong">' in html, "организация адресата — полужирным"
    assert "Подписано электронной подписью" in html and meta["signed_text"] in html
    assert 'class="rt-fcols"' in html and "Руководство" in html


async def test_draft_letter_has_no_number_in_the_info_block_and_no_verification(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    doc = await draft_letter(client, container, staff["manager"])
    payload = await make_ready(client, container, deferred, staff["manager"], doc)
    assert payload["draft"] is True
    assert not [row for row in payload["meta"]["info"] if row["role"] == "verify"]
    html = sheet(payload)
    assert (
        "без номера" in html
        and "Подписано электронной подписью" not in html
        and '<div class="rt-sign-qrbox">' not in html
    )


async def test_letter_in_uzbek_has_uzbek_labels_in_the_owner_alphabet(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    body = copy.deepcopy(BODY)
    body["lang"] = "uz"
    created = await client.post(
        "/api/v1/documents",
        json=letter_json(letter={**letter_json()["letter"], "body": body}),
        headers=staff["manager"].headers,
    )
    assert created.status_code == 201, created.text
    async with container.session_factory() as session:
        document = await session.get(Document, created.json()["id"])
        assert document is not None
        payload, _ = await renders.build_payload(session, document)
    labels = [row["label"] for row in payload["meta"]["info"]]
    assert payload["meta"]["kind_label"] == "Xat"
    assert labels[:2] == ["Çiqiş №", "Sana"] and "Ijroçi" in labels and "Poçta" in labels
    assert all(ch not in label for label in labels for ch in "ʻʼ'"), "только Ö Ğ Ş Ç, без Oʻ Gʻ Sh Ch"
    old_digraphs = re.compile(r"sh|ch|oʻ|gʻ", re.IGNORECASE)
    printed = [*labels, GRID_LABELS["verify"]["uz"], GRID_LABELS["internal_note"]["uz"], STAMP["uz"], EXECUTOR["uz"]]
    assert not [text for text in printed if old_digraphs.search(text)]
    assert EXECUTOR["uz"].strip(": ") == "Ijroçi", "the footer executor line and the info block spell the word alike"
