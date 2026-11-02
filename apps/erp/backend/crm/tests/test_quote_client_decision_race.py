"""A1 волны 18a: гонка «сотрудник отмечает решение клиента» ↔ «клиент принимает КП в кабинете» — реальные соединения Postgres.

Окно между «прочитал КП (SENT)» и «записал решение» растянуто паузой после чтения у первого участника: без блокировки строки
КП (`lifecycle_accept._locked_quote`, `select_for_update`) второй участник тоже читает SENT и тоже принимает — два акцепта,
два события, два журнала. С блокировкой второй ждёт коммита первого, видит APPROVED и получает отказ. Мутационная проверка —
в описании PR (ORCHESTRATOR §4.1): без `select_for_update` тест краснеет.
"""

from __future__ import annotations

import threading
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.utils import timezone
from integration.tests import world as w

from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import ActivityLog, Quote
from crm.services.quotes import lifecycle_accept
from crm.services.quotes.client_decision import ClientDecisionInput, record_client_decision
from crm.tests.projects_world import PDF, pw  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def lookups():
    """Транзакционный тест после себя очищает таблицы: справочники, которые трогает цепочка акцепта, заводим сами."""
    from crm.models import ContractStatus, DealStage, QuoteStatus

    for model, codes in (
        (QuoteStatus, ("SENT", "APPROVED", "REJECTED")),
        (DealStage, (DealStageCode.QUOTE_SENT, DealStageCode.CONTRACT_SIGNED, DealStageCode.CALCULATING)),
        (ContractStatus, ("DRAFT", "PENDING_CLIENT", "CANCELLED")),
    ):
        for order, code in enumerate(codes):
            model.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})


def _staff_decision(pw, quote):  # noqa: F811
    return record_client_decision(
        quote.pk,
        pw.manager,
        ClientDecisionInput(
            decision="accept",
            channel="email",
            counterparty_person="Каримов А.",
            occurred_on=timezone.localdate().isoformat(),
            comment="Письмо клиента",
            evidence=SimpleUploadedFile("letter.pdf", PDF, content_type="application/pdf"),
        ),
    )


def _online_accept(quote):
    lifecycle_accept.perform_quote_acceptance(quote.pk, contact_email="i@client.uz")
    return True


@pytest.mark.parametrize("staff_first", [True, False], ids=["staff_first", "client_first"])
def test_staff_record_and_online_acceptance_accept_the_quote_once(pw, monkeypatch, staff_first):  # noqa: F811
    deal = w.make_deal(pw.client, DealStageCode.QUOTE_SENT)
    deal.manager = pw.manager
    deal.save(update_fields=["manager"])
    quote = w.add_quote(deal, 1, QuoteStatusCode.SENT, "7000000")

    original = lifecycle_accept._locked_quote
    first_read = threading.Event()

    def slow_locked_quote(quote_id):
        found = original(quote_id)
        if not first_read.is_set():
            first_read.set()
            time.sleep(1.5)  # первый держит строку: второй либо ждёт (блокировка), либо читает SENT (гонка)
        return found

    monkeypatch.setattr(lifecycle_accept, "_locked_quote", slow_locked_quote)

    results: dict = {}

    def run(name, call):
        try:
            results[name] = call()
        except ValueError as exc:
            results[name] = exc
        finally:
            connection.close()

    staff = threading.Thread(target=run, args=("staff", lambda: _staff_decision(pw, quote)))
    client = threading.Thread(target=run, args=("client", lambda: _online_accept(quote)))
    first, second = (staff, client) if staff_first else (client, staff)
    first.start()
    assert first_read.wait(timeout=30), "первый участник не дошёл до чтения КП"
    second.start()
    for thread in (first, second):
        thread.join(timeout=60)

    staff_ok = isinstance(results.get("staff"), tuple) and results["staff"][1] is None
    client_ok = results.get("client") is True
    assert staff_ok != client_ok, f"принять КП должен ровно один: {results}"
    if not staff_ok:
        assert results["staff"] == (None, "QUOTE_NOT_SENT")
    assert ActivityLog.objects.filter(event_code="quote.accepted", entity_id=quote.pk).count() == 1
    assert Quote.objects.get(pk=quote.pk).status.code == QuoteStatusCode.APPROVED
