"""AI #8 conversational заявка builder — disabled→empty, items returned, endpoint guards.

The Claude client is stubbed (no paid/nondeterministic calls); we assert the deterministic
contract: gated on AI_IMPORT_ENABLED, free-text → structured items, noise rows dropped,
endpoint 400/503 guards. Catalog matching is stubbed off (attach_candidates=False / no DB).
"""

from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser


def _stub_response(items):
    text = __import__("json").dumps({"items": items})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


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
    monkeypatch.setattr(
        "sourcing.services_ai_conversational._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
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
    monkeypatch.setattr(
        "sourcing.services_ai_conversational._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    from sourcing.services_ai_conversational import build_request_from_text

    items = build_request_from_text("нужны болты М12, 100 штук", attach_candidates=False)["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Болт М12"


@pytest.mark.django_db
def test_compose_endpoint_guards(settings, monkeypatch):
    # Spy: every guarded path (missing/blank text, AI disabled) MUST return BEFORE the paid
    # Claude call — this proves the no-paid-call contract, not just the status code.
    import sourcing.services_ai_conversational as conv

    monkeypatch.setattr(conv, "_client", lambda: pytest.fail("paid LLM call reached on a guarded compose path"))
    settings.AI_IMPORT_ENABLED = True
    user = CustomUser.objects.create_user(email="cw@x.test", username="cw@x.test", password="pw", is_active=True)
    client = APIClient()
    client.force_authenticate(user)
    # missing text → 400
    assert client.post("/api/v1/sourcing/compose-request/", {}, format="json").status_code == 400
    # blank text → 400
    assert client.post("/api/v1/sourcing/compose-request/", {"text": "  "}, format="json").status_code == 400
    # disabled → 503
    settings.AI_IMPORT_ENABLED = False
    response = client.post("/api/v1/sourcing/compose-request/", {"text": "болты"}, format="json")
    assert response.status_code == 503
