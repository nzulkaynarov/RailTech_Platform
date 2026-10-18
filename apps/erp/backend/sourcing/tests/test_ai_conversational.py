"""AI #8 conversational заявка builder — disabled→empty, items returned.

The LiteLLM gateway is faked (ai.testing.FakeGateway) (no paid/nondeterministic calls); we assert the deterministic
contract: gated on AI_IMPORT_ENABLED, free-text → structured items, noise rows dropped.
The HTTP endpoints left with the buyer path (FIX-13). Catalog matching is stubbed off (attach_candidates=False / no DB).
"""

import pytest
from ai.testing import install_fake_gateway


def _stub_response(items):
    return {"items": items}


@pytest.mark.django_db
def test_compose_disabled_returns_empty(settings):
    settings.AI_IMPORT_ENABLED = False
    from sourcing.services_ai_conversational import build_request_from_text

    assert build_request_from_text("нужны тормозные колодки, 4 комплекта") == {"items": []}


@pytest.mark.django_db
def test_compose_empty_text_returns_empty(settings):
    settings.AI_IMPORT_ENABLED = True
    from sourcing.services_ai_conversational import build_request_from_text

    assert build_request_from_text("   ") == {"items": []}


@pytest.mark.django_db
def test_compose_returns_structured_items(settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response(
        [
            {
                "name": "Тормозная колодка",
                "name_canonical": "Тормозная колодка",
                "quantity": 4,
                "unit": "компл.",
                "mpn": "",
                "gost_drawing": "",
                "note": "на вагон",
            },
            {
                "name": "Подшипник буксовый",
                "name_canonical": "Подшипник буксовый",
                "quantity": 1,
                "unit": "",
                "mpn": "",
                "gost_drawing": "",
                "note": "",
            },
        ]
    )
    install_fake_gateway(monkeypatch).reply_json(fake)
    from sourcing.services_ai_conversational import build_request_from_text

    # attach_candidates=False keeps the test off the DB/catalog match path.
    result = build_request_from_text(
        "нужны тормозные колодки на вагон, 4 комплекта, и подшипники буксовые",
        attach_candidates=False,
    )
    items = result["items"]
    assert len(items) == 2
    assert items[0]["name"] == "Тормозная колодка"
    assert items[0]["quantity"] == 4
    assert items[0]["unit"] == "компл."
    assert items[0]["candidates"] == []
    # qty defaults to 1 when unstated.
    assert items[1]["quantity"] == 1


@pytest.mark.django_db
def test_compose_drops_noise_rows(settings, monkeypatch):
    """A row with neither a name nor any identifying code is noise → dropped (Rule 1 hygiene)."""
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response(
        [
            {
                "name": "Болт М12",
                "name_canonical": "Болт М12",
                "quantity": 100,
                "unit": "шт",
                "mpn": "",
                "gost_drawing": "",
                "note": "",
            },
            {"name": "", "name_canonical": "", "quantity": 1, "unit": "", "mpn": "", "gost_drawing": "", "note": ""},
        ]
    )
    install_fake_gateway(monkeypatch).reply_json(fake)
    from sourcing.services_ai_conversational import build_request_from_text

    items = build_request_from_text("нужны болты М12, 100 штук", attach_candidates=False)["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Болт М12"
