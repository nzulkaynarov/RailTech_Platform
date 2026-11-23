"""Шаблоны писем и служебок (TPL-4, план 3.6): встроенные, языки, «по умолчанию», «Вернуть», предпросмотр."""

import copy
from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, validate
from tests.test_api_auth import assert_error
from tests.test_letterhead_letters import deliver_letterhead

pytestmark = pytest.mark.pg
BASE = "/api/v1/templates"
PREVIEW = "/api/v1/template-previews"


def body(lang: str, text: str) -> dict[str, Any]:
    return {
        "version": 1,
        "lang": lang,
        "doc": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]},
    }


async def listed(client: httpx.AsyncClient, who: Person, kind: str | None = None) -> list[dict[str, Any]]:
    response = await client.get(BASE, params={"kind": kind} if kind else None, headers=who.headers)
    assert response.status_code == 200, response.text
    validate("LetterTemplateList", response.json())
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_builtins_appear_once_with_defaults_and_languages(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    first = await listed(client, staff["manager"])
    again = await listed(client, staff["registrar"])
    assert [t["id"] for t in first] == [t["id"] for t in again]
    letter = next(t for t in first if t["kind"] == "letter")
    assert (letter["name"], letter["origin"], letter["is_default"], letter["changed"]) == (
        "Деловое письмо",
        "builtin",
        True,
        False,
    )
    assert letter["languages"] == ["ru", "uz", "en"]
    assert [t["kind"] for t in await listed(client, staff["manager"], "memo")] == ["memo"]


async def test_registrar_edits_resets_and_switches_default_manager_only_reads(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    registrar, manager = staff["registrar"], staff["manager"]
    builtin = next(t for t in await listed(client, registrar) if t["kind"] == "letter")
    custom = {
        "kind": "letter",
        "name": "Ответ налоговой",
        "variants": {"ru": body("ru", "Направляем пояснения."), "uz": body("uz", "Tushuntirish yuboramiz.")},
        "is_default": True,
    }
    assert_error(await client.post(BASE, json=custom, headers=manager.headers), 403, "FORBIDDEN")
    bad = {**custom, "variants": {"uz": body("ru", "не тот язык")}}
    assert_error(await client.post(BASE, json=bad, headers=registrar.headers), 422, "VALIDATION_FAILED")
    assert_error(
        await client.post(BASE, json={**custom, "variants": {}}, headers=registrar.headers), 422, "VALIDATION_FAILED"
    )

    created = await client.post(BASE, json=custom, headers=registrar.headers)
    assert created.status_code == 201, created.text
    made = created.json()
    validate("LetterTemplate", made)
    assert (made["origin"], made["languages"], made["is_default"]) == ("custom", ["ru", "uz"], True)
    letters = {t["id"]: t for t in await listed(client, registrar, "letter")}
    assert letters[builtin["id"]]["is_default"] is False, "по умолчанию — один шаблон на вид"

    edited = copy.deepcopy(builtin)
    put = {
        "kind": "letter",
        "name": edited["name"],
        "variants": {"ru": body("ru", "Свой текст")},
        "is_default": False,
        "active": True,
    }
    changed = await client.put(f"{BASE}/{builtin['id']}", json=put, headers=registrar.headers)
    assert changed.status_code == 200, changed.text
    assert (changed.json()["changed"], changed.json()["languages"]) == (True, ["ru"])
    reset = await client.post(f"{BASE}/{builtin['id']}/reset", headers=registrar.headers)
    assert (reset.json()["changed"], reset.json()["languages"]) == (False, ["ru", "uz", "en"])

    assert_error(await client.delete(f"{BASE}/{builtin['id']}", headers=registrar.headers), 409, "CONFLICT")
    assert_error(await client.delete(f"{BASE}/{made['id']}", headers=registrar.headers), 409, "CONFLICT")
    assert_error(await client.post(f"{BASE}/{made['id']}/reset", headers=registrar.headers), 409, "CONFLICT")


async def test_preview_needs_the_letterhead_and_is_served_only_as_a_preview(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    manager = staff["manager"]
    request = {"body": body("uz", "Hurmatli hamkasblar!")}
    assert_error(await client.post(PREVIEW, json=request, headers=manager.headers), 409, "CONFLICT")
    await deliver_letterhead(client, container)
    first = await client.post(PREVIEW, json=request, headers=manager.headers)
    assert first.status_code == 202, first.text
    validate("TemplatePreview", first.json())
    again = await client.post(PREVIEW, json=request, headers=manager.headers)
    assert again.json()["hash"] == first.json()["hash"], "тот же ввод — тот же рендер из кэша"
    state = await client.get(f"{PREVIEW}/{first.json()['hash']}", headers=manager.headers)
    assert state.status_code == 200 and state.json()["status"] in ("pending", "ready")
    assert (await client.get(f"{PREVIEW}/{'0' * 64}", headers=manager.headers)).status_code == 404


async def test_memo_preview_is_the_compact_sheet_without_the_letter_word_window_and_outgoing_number(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    from rt_docs import Layout
    from rt_docs.prepare import document_html, prepare

    from app.models import DocumentRender
    from app.services import render_process

    await deliver_letterhead(client, container)
    htmls: dict[str, str] = {}
    for kind in ("letter", "memo"):
        request = {"body": body("ru", "Коллеги!"), "kind": kind}
        answer = await client.post(PREVIEW, json=request, headers=staff["manager"].headers)
        assert answer.status_code == 202, answer.text
        async with container.session_factory() as session:
            row = await session.get(DocumentRender, answer.json()["hash"])
            assert row is not None
            payload = row.payload
        letterhead, meta = render_process.render_inputs(payload, None, None)
        prepared = prepare(
            payload["body"],
            letterhead=letterhead,
            layout=Layout(payload["layout"]),
            meta=meta,
            highlight_missing=False,
            draft=True,
        )
        htmls[kind] = document_html(prepared, page_numbers=True)
    assert "Служебная записка" in htmls["memo"]
    for fragment in ("Письмо", "Исх. №", '<div class="rt-id-window'):
        assert fragment not in htmls["memo"], fragment
    assert "Письмо" in htmls["letter"] and "Исх. №" in htmls["letter"], "the letter preview is unchanged"


async def test_former_erp_samples_are_letter_templates_in_three_languages(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    """ДОК-13: «Гарантийное письмо», «Сопроводительное письмо» и «Претензия» — встроенные шаблоны писем на бланке."""
    letters = {t["name"]: t for t in await listed(client, staff["manager"], "letter")}
    for name in ("Гарантийное письмо", "Сопроводительное письмо", "Претензия"):
        row = letters[name]
        assert (row["origin"], row["changed"], row["is_default"]) == ("builtin", False, False)
        assert row["languages"] == ["ru", "uz", "en"]
    assert letters["Деловое письмо"]["is_default"] is True  # new built-ins never take the default away
    # Uzbek is in the new Latin alphabet: none of the old o‘ / g‘ / sh / ch digraph spellings
    for name in ("Гарантийное письмо", "Сопроводительное письмо", "Претензия"):
        text = str(letters[name]["variants"]["uz"])
        assert "o‘" not in text and "O‘" not in text and "g‘" not in text
