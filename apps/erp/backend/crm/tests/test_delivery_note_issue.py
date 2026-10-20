"""FIX-55 / m2 D-6: накладная получает итоговый номер при выпуске, а язык печати разрешается для всех документов.

Раньше номер присваивался только при первой печати (воркер), поэтому в портале накладная жила как `DN-<id>` и меняла
номер после рендера; рендер не ставился при отгрузке. Теперь при переходе отгрузки в «выпущенный» статус номер
присваивается один раз по схеме нумерации и ставится рендер PDF. Заодно: `_document_language` искал модели в приложении
`crm` (где их нет) и молча падал в язык платформы с предупреждением «Could not resolve recipient language».
"""

import logging

import pytest

from crm import services as crm_services
from crm.constants import FulfillmentStatusCode
from crm.models import Fulfillment
from crm.services.fulfillment import delivery_note_number
from crm.tests.test_document_language import _buyer_with_languages
from crm.tests.test_fulfillment_service import lookups, world  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def render_calls(monkeypatch):
    calls = []
    monkeypatch.setattr("crm.tasks.render_document_pdf.delay", lambda doc_type, pk: calls.append((doc_type, pk)))
    return calls


def _ship(world, status=FulfillmentStatusCode.SHIPPED):  # noqa: F811
    return crm_services.update_fulfillment_status(world["deal"].id, world["superuser"], status)


def test_number_is_assigned_when_the_shipment_is_issued(
    world, render_calls, django_capture_on_commit_callbacks
):  # noqa: F811
    fulfillment = crm_services.ensure_fulfillment(world["deal"])
    assert not fulfillment.note_number

    with django_capture_on_commit_callbacks(execute=True):
        obj, err = _ship(world)

    assert err is None
    obj.refresh_from_db()
    assert obj.note_number, "номер должен быть присвоен при выпуске"
    assert obj.note_number != f"DN-{obj.id}", "итоговый номер из схемы, а не легаси DN-<id>"
    assert delivery_note_number(obj) == obj.note_number
    assert render_calls == [("delivery_note", obj.pk)], "рендер ставится при выпуске"


def test_number_is_stable_across_later_statuses(world, render_calls, django_capture_on_commit_callbacks):  # noqa: F811
    crm_services.ensure_fulfillment(world["deal"])
    with django_capture_on_commit_callbacks(execute=True):
        first, _ = _ship(world)
    number = Fulfillment.objects.get(pk=first.pk).note_number

    with django_capture_on_commit_callbacks(execute=True):
        _ship(world, FulfillmentStatusCode.IN_TRANSIT)
        _ship(world, FulfillmentStatusCode.DELIVERED)

    assert Fulfillment.objects.get(pk=first.pk).note_number == number
    assert len(render_calls) == 1, "выпуск один раз: повторные статусы не ставят рендер и не меняют номер"


def test_pending_shipment_has_no_number_and_no_render(
    world, render_calls, django_capture_on_commit_callbacks
):  # noqa: F811
    with django_capture_on_commit_callbacks(execute=True):
        fulfillment = crm_services.ensure_fulfillment(world["deal"])
    assert not Fulfillment.objects.get(pk=fulfillment.pk).note_number
    assert render_calls == []


@pytest.mark.parametrize("doc_type", ["delivery_note", "contract", "invoice", "act", "receipt"])
def test_document_models_resolve_for_the_language_lookup(doc_type):
    from django.apps import apps

    from crm.tasks import _DOCUMENT_LANGUAGE_MODELS

    app_label, model_name = _DOCUMENT_LANGUAGE_MODELS[doc_type][:2]
    assert apps.get_model(app_label, model_name)


def test_delivery_note_language_follows_the_buyer(lookups, caplog, render_calls):  # noqa: F811
    from crm.models import Deal, DealStage
    from crm.tasks import _document_language

    company = _buyer_with_languages(["en", "en"], "9940000001")
    deal = Deal.objects.create(title="EN", company=company, stage=DealStage.objects.get(code="DRAFT"))
    fulfillment = crm_services.ensure_fulfillment(deal)

    with caplog.at_level(logging.WARNING, logger="crm.tasks"):
        language = _document_language("delivery_note", fulfillment.pk)

    assert language == "en"
    assert "Could not resolve recipient language" not in caplog.text


def test_document_created_event_carries_the_final_number(world, render_calls, monkeypatch):  # noqa: F811
    """Событие `document.created` для CRM уходит на переходе в «выпущенный» и несёт итоговый номер, а не `DN-<id>`."""
    sent = []
    monkeypatch.setattr("integration.services.webhooks.emit_document_created", lambda document: sent.append(document))
    crm_services.ensure_fulfillment(world["deal"])

    obj, _ = _ship(world)

    obj.refresh_from_db()
    assert len(sent) == 1, "одно событие на выпуск"
    assert sent[0].kind == "waybill"
    assert sent[0].number == obj.note_number != f"DN-{obj.pk}"
