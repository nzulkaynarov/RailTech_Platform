"""AI #4 deal-chat reply assist — disabled→empty, visibility scoping, draft surfaces.

The Claude client is stubbed (no paid/nondeterministic calls); we assert the
deterministic contract:
- gated on AI_IMPORT_ENABLED → {"draft": ""} when off (never 500s the flow),
- the SAME deal-visibility scoping the chat uses (a stranger gets an empty draft),
- an empty thread yields no paid call and an empty draft,
- a real thread surfaces the model's stubbed draft.
"""

from types import SimpleNamespace

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Message


def _stub_response(draft):
    text = __import__("json").dumps({"draft": draft})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


def _make_deal_with_chat():
    DealStage.objects.get_or_create(code="SOURCING", defaults={"name": "Sourcing", "sort_order": 30})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})

    buyer = CustomUser.objects.create_user(
        email="aichat-buyer@x.test", username="aichat-buyer@x.test", password="pw", is_active=True
    )
    company = Company.objects.create(name="AI Chat Co", inn="700700700")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=buyer, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True
    )
    deal = Deal.objects.create(
        title="AI Chat Deal", company=company, client=buyer, stage=DealStage.objects.get(code="SOURCING")
    )
    Message.objects.create(deal=deal, sender=buyer, text="Здравствуйте, какие сроки поставки?", message_type="CHAT")
    return buyer, deal


@pytest.mark.django_db
def test_suggest_reply_disabled_returns_empty(settings):
    settings.AI_IMPORT_ENABLED = False
    from crm.services import suggest_chat_reply

    buyer, deal = _make_deal_with_chat()
    assert suggest_chat_reply(deal.id, buyer) == {"draft": ""}


@pytest.mark.django_db
def test_suggest_reply_surfaces_draft(settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response("Добрый день! Уточним сроки и вернёмся с ответом в ближайшее время.")
    monkeypatch.setattr(
        "crm.services.ai_chat._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    from crm.services import suggest_chat_reply

    buyer, deal = _make_deal_with_chat()
    result = suggest_chat_reply(deal.id, buyer)
    assert result["draft"].startswith("Добрый день!")


@pytest.mark.django_db
def test_suggest_reply_scopes_to_deal_access(settings, monkeypatch):
    """A user who cannot access the deal's chat gets an empty draft — no paid call."""
    settings.AI_IMPORT_ENABLED = True
    called = {"hit": False}

    def _boom():
        called["hit"] = True
        raise AssertionError("client must not be called for an unauthorized user")

    monkeypatch.setattr("crm.services.ai_chat._client", _boom)
    from crm.services import suggest_chat_reply

    _, deal = _make_deal_with_chat()
    stranger = CustomUser.objects.create_user(
        email="aichat-stranger@x.test", username="aichat-stranger@x.test", password="pw", is_active=True
    )
    assert suggest_chat_reply(deal.id, stranger) == {"draft": ""}
    assert called["hit"] is False


@pytest.mark.django_db
def test_suggest_reply_empty_thread_skips_call(settings, monkeypatch):
    """No human messages → empty draft, no paid Claude call."""
    settings.AI_IMPORT_ENABLED = True
    DealStage.objects.get_or_create(code="SOURCING", defaults={"name": "Sourcing", "sort_order": 30})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    buyer = CustomUser.objects.create_user(
        email="aichat-empty@x.test", username="aichat-empty@x.test", password="pw", is_active=True
    )
    company = Company.objects.create(name="Empty Co", inn="700700701")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=buyer, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True
    )
    deal = Deal.objects.create(
        title="Empty", company=company, client=buyer, stage=DealStage.objects.get(code="SOURCING")
    )

    def _boom():
        raise AssertionError("client must not be called for an empty thread")

    monkeypatch.setattr("crm.services.ai_chat._client", _boom)
    from crm.services import suggest_chat_reply

    assert suggest_chat_reply(deal.id, buyer) == {"draft": ""}


@pytest.mark.django_db
def test_suggest_reply_endpoint_503_when_disabled(settings):
    """Endpoint contract: AI off → 503 (neutral, never 500s the flow). The route is
    wired in core/urls.py (shared file owned by the orchestrator); if it is not yet
    registered in this checkout, skip rather than fail this bucket's standalone run."""
    from django.urls import NoReverseMatch, reverse
    from rest_framework.test import APIClient

    buyer, deal = _make_deal_with_chat()
    try:
        url = reverse("suggest-chat-reply", kwargs={"deal_id": deal.id})
    except NoReverseMatch:
        pytest.skip("suggest-chat-reply route not wired yet (orchestrator registers it in core/urls.py)")

    settings.AI_IMPORT_ENABLED = False
    client = APIClient()
    client.force_authenticate(buyer)
    response = client.post(url, {}, format="json")
    assert response.status_code == 503
