"""События ERP публикуются из сервисного слоя в транзакции изменения (B3, runbook волны 11 §3).

* золотой путь заявка → КП → договор → счёт → оплата → поставка на настоящих сервисах публикует цепочку событий, и каждое
  проходит схему контракта;
* каждый из 24 типов `uz.railtech.erp.*.v1` рождается в своём сервисе (`test_every_event_type_is_published_by_its_service`);
* откат транзакции — нет события (в обе стороны: событие не переживает откат, откат не прячет событие другого действия);
* ошибка публикации (в том числе `data` не по схеме) откатывает само изменение;
* в ERP нет `except Exception` вокруг публикации, сигналов Django и вебхуков.
"""

from __future__ import annotations

import ast
import datetime
from pathlib import Path

import pytest
from django.db import transaction
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping
from integration.services import events
from integration.tests import bus_support
from parties.models import Contact
from rt_bus import EventValidationError

from crm import services as crm_services
from crm.models import Act, ActStatus, Deal, DealStage, Invoice, Quote, QuoteStatus
from crm.services.quotes import QuoteCalculationService, QuoteLifecycleService
from crm.tests.test_act_issuer_actions import world  # noqa: F401
from crm.tests.test_golden_path import _build_quote_with_items, buyer, deal, lookups, manager  # noqa: F401

pytestmark = pytest.mark.django_db

CRM_CLIENT_ID = 4242


@pytest.fixture
def mapped(buyer):  # noqa: F811
    _, company = buyer
    CrmClientMapping.objects.create(company=company, crm_client_id=CRM_CLIENT_ID)
    return company


@pytest.fixture
def mapped_world(world):  # noqa: F811
    CrmClientMapping.objects.create(company=world["deal"].company, crm_client_id=CRM_CLIENT_ID + 1)


def _move(deal, manager, *targets):  # noqa: F811
    for target in targets:
        _, error = crm_services.transition_deal_stage(deal, target, actor=manager)
        assert error is None, f"{target}: {error}"


def _send_quote(deal, manager):  # noqa: F811
    _move(deal, manager, "SOURCING", "CALCULATING")
    quote = _build_quote_with_items(deal, manager)
    QuoteCalculationService.recalculate_quote(quote.id)
    quote.status = QuoteStatus.objects.get(code="READY_TO_SEND")
    quote.save(update_fields=["status"])
    return QuoteLifecycleService.send_to_client(quote.id, manager)


# ── Золотой путь ────────────────────────────────────────────────────────────────────────────────────


def test_golden_path_publishes_the_events_of_the_whole_chain_in_the_same_transactions(
    deal, buyer, manager, mapped  # noqa: F811
):
    buyer_user, _ = buyer
    quote = _send_quote(deal, manager)
    sent_types = bus_support.types()
    assert "quote.sent" in sent_types and "document.created" in sent_types
    assert sent_types.count("deal.stage_changed") == 2  # request → quoting, quoting → quote_sent
    quote_sent = bus_support.only("quote.sent")
    assert quote_sent["data"]["payload"]["erp_quote_id"] == quote.pk
    assert (
        quote_sent["data"]["erp_company_id"] == deal.company_id and quote_sent["data"]["crm_client_id"] == CRM_CLIENT_ID
    )
    assert quote_sent["source"] == "rt://erp" and quote_sent["subject"] == deal.number  # ERP-09: номер ЗВ

    quote = QuoteLifecycleService.approve_quote(quote.id, buyer_user)
    contract, error = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    assert error is None
    contract, error = crm_services.sign_contract_by_client(contract.id, manager)
    assert error is None
    signed = bus_support.published("contract.signed")
    assert [e["data"]["payload"]["by"] for e in signed] == ["client"]
    contract, error = crm_services.sign_contract_by_manager(contract.id, manager)
    assert error is None
    assert [e["data"]["payload"]["by"] for e in bus_support.published("contract.signed")] == ["client", "both"]
    assert len(bus_support.published("deal.won")) == 1, "подпись обеими сторонами закрывает сделку как выигранную"

    invoice, error = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    assert error is None
    assert not bus_support.published("invoice.issued"), "черновик счёта клиенту не выпущен"
    invoice, error = crm_services.issue_invoice(invoice, manager)
    assert error is None
    assert bus_support.only("invoice.issued")["data"]["payload"]["erp_invoice_id"] == invoice.pk
    _, error = crm_services.record_payment(
        invoice.id, manager, amount=invoice.total_incl_vat, paid_at=timezone.localdate(), manual=True
    )
    assert error is None
    assert bus_support.only("invoice.paid")["data"]["payload"]["erp_invoice_id"] == invoice.pk

    crm_services.ensure_fulfillment(deal)
    _, error = crm_services.update_fulfillment_status(deal.id, manager, "ACCEPTED")
    assert error is None

    published = bus_support.published()
    assert published, "цепочка не пуста"
    for envelope in published:
        bus_support.assert_matches_contract(envelope)
        assert envelope["data"]["crm_client_id"] == CRM_CLIENT_ID


def test_company_not_linked_to_crm_publishes_nothing_along_the_whole_chain(deal, buyer, manager):  # noqa: F811
    buyer_user, _ = buyer
    quote = _send_quote(deal, manager)
    quote = QuoteLifecycleService.approve_quote(quote.id, buyer_user)
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, manager)
    crm_services.sign_contract_by_manager(contract.id, manager)
    assert bus_support.published() == []


# ── Откат: события нет, а ошибка публикации откатывает изменение ─────────────────────────────────────


def test_rolled_back_transaction_leaves_no_event(deal, manager, mapped):  # noqa: F811
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            _, error = crm_services.transition_deal_stage(deal, "SOURCING", actor=manager)
            assert error is None
            assert bus_support.types() == ["deal.stage_changed"], "событие записано вместе с изменением"
            raise RuntimeError("позже в той же транзакции что-то упало")
    assert bus_support.published() == [], "откат убрал и изменение, и событие"
    deal.refresh_from_db()
    assert deal.stage.code == "DRAFT"


def test_a_rollback_of_one_action_does_not_hide_the_event_of_the_previous_one(deal, manager, mapped):  # noqa: F811
    _move(deal, manager, "SOURCING")
    assert bus_support.types() == ["deal.stage_changed"]
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            crm_services.transition_deal_stage(deal, "CLOSED_LOST", actor=manager)
            assert bus_support.types() == ["deal.stage_changed", "deal.stage_changed", "deal.lost"]
            raise RuntimeError("boom")
    assert bus_support.types() == [
        "deal.stage_changed"
    ], "осталось только событие первого, уже зафиксированного действия"


def test_publication_failure_rolls_the_change_back(deal, manager, mapped, monkeypatch):  # noqa: F811
    """Ошибка публикации (шина недоступна, `data` не по схеме) — исключение наружу и откат изменения."""

    def boom(*args, **kwargs):
        raise EventValidationError("data of uz.railtech.erp.deal.stage_changed.v1 is invalid")

    monkeypatch.setattr(events, "publish_deal_stage_changed", boom)
    with pytest.raises(EventValidationError):
        crm_services.transition_deal_stage(deal, "SOURCING", actor=manager)
    deal.refresh_from_db()
    assert deal.stage.code == "DRAFT", "стадия не сменилась: изменение откатилось вместе с неудавшейся публикацией"
    assert bus_support.published() == []


def test_data_not_by_the_schema_rolls_back_the_real_service(deal, buyer, manager, mapped, monkeypatch):  # noqa: F811
    """Без подмены публикатора: настоящая шина отвергает кривое `data`, и КП остаётся неотправленным."""
    _move(deal, manager, "SOURCING", "CALCULATING")
    quote = _build_quote_with_items(deal, manager)
    QuoteCalculationService.recalculate_quote(quote.id)
    quote.status = QuoteStatus.objects.get(code="READY_TO_SEND")
    quote.save(update_fields=["status"])
    bus_support.reset()
    real = events.build_deal_ref

    def broken_ref(deal_):
        ref = real(deal_)
        ref["unexpected"] = "лишнее поле"  # additionalProperties: false
        return ref

    monkeypatch.setattr("integration.services.event_builders.build_deal_ref", broken_ref)
    with pytest.raises(EventValidationError):
        QuoteLifecycleService.send_to_client(quote.id, manager)
    quote.refresh_from_db()
    assert quote.status.code == "READY_TO_SEND" and quote.frozen_at is None and not quote.public_access_token
    assert bus_support.published() == []


def test_publish_outside_a_transaction_is_an_error_not_silence(mapped, buyer):  # noqa: F811
    """Бизнес-код обязан публиковать в транзакции: тест фиксирует правило `NotInTransactionError`."""
    from integration.bus import get_bus
    from rt_bus import NotInTransactionError

    bus = get_bus()
    with pytest.raises(NotInTransactionError):
        # `django_db` держит тест в транзакции — снимаем признак, чтобы увидеть контракт библиотеки.
        from django.db import connection

        in_atomic = connection.in_atomic_block
        connection.in_atomic_block = False
        try:
            bus.publish("uz.railtech.erp.invite.sent.v1", {})
        finally:
            connection.in_atomic_block = in_atomic


# ── Остальные типы: каждый из своего сервиса ───────────────────────────────────────────────────────


def test_every_event_type_is_published_by_its_service(deal, buyer, manager, mapped, settings):  # noqa: F811
    from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
    from portal.services.acceptance import request_acceptance_code
    from portal.services.invitation import invite_contact_to_portal
    from portal.services.requests import create_client_request
    from sales.models import DeliveryLine
    from sales.services.delivery_lines import accept_delivery_line, dispute_delivery_line, sync_delivery_lines

    from crm.services.billing import generate_act, reject_act, sign_act
    from crm.services.public_page import record_quote_view
    from crm.tasks import send_payment_reminders

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    buyer_user, company = buyer
    contact = Contact.objects.create(
        company=company, name="Иван Петров", email="ivan@buyer.example", can_act=True, telegram_user_id=424242
    )
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)

    # request.created — запрос из Cabinet (портал)
    create_client_request(
        company, contact, summary="Нужны рельсы", lines=[{"text": "Р65", "quantity": "5"}], attachments=[]
    )
    # quote.sent, document.created(quote), deal.stage_changed — отправка КП
    quote = _send_quote(deal, manager)
    # quote.viewed — клиент открыл публичную страницу
    assert record_quote_view(quote) is True
    # quote.acceptance_code_requested — код акцепта контакту с Telegram и сопоставлением в CRM
    assert request_acceptance_code(quote, contact)["channel"] == "telegram"
    # quote.rejected — клиент отклонил другое КП (из Cabinet, контактом портала)
    from integration.tests.world import add_quote, make_deal

    from crm.services.quotes.lifecycle_accept import perform_quote_rejection

    rejected = add_quote(make_deal(company, "QUOTE_SENT", title="Отклонённая"), 1, "SENT", "1000")
    perform_quote_rejection(rejected.id, rejected_by_user=None, reason="Дорого", portal_contact=contact)
    # quote.ready_for_approval — визы собраны, КП уходит директору в EDS (EDS-03)
    from crm.services.eds_quote_approval import request_director_approval

    for_director = add_quote(make_deal(company, "CALCULATING", title="КП директору"), 1, "PENDING_APPROVAL", "1000")
    request_director_approval(for_director, manager)
    # quote.accepted + document.created(contract) + contract.signed ×2 + deal.won — акцепт и подписи
    quote = QuoteLifecycleService.approve_quote(quote.id, buyer_user)
    contract, _ = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    crm_services.sign_contract_by_client(contract.id, manager)
    crm_services.sign_contract_by_manager(contract.id, manager)
    # invoice.issued, invoice.overdue (напоминание по просроченному), invoice.paid
    invoice, _ = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    invoice, _ = crm_services.issue_invoice(invoice, manager)
    Invoice.objects.filter(pk=invoice.pk).update(due_date=timezone.localdate() - datetime.timedelta(days=30))
    assert send_payment_reminders(grace_days=3) == {"reminded": 1}
    assert len(bus_support.published("invoice.overdue")) == 1
    invoice.refresh_from_db()
    _, error = crm_services.record_payment(
        invoice.id, manager, amount=invoice.total_incl_vat, paid_at=timezone.localdate(), manual=True
    )
    assert error is None
    # act.issued, act.returned, act.accepted
    act, error = generate_act(invoice.id, manager)
    assert error is None, error
    assert reject_act(act.id, None, "Не совпадает количество", portal_contact=contact)[1] is None
    Act.objects.filter(pk=act.pk).update(status=ActStatus.objects.get(code="ISSUED"), rejection_reason="")
    assert sign_act(act.id, None, portal_contact=contact)[1] is None
    # delivery.status_changed, delivery.eta_changed, document.created(waybill)
    crm_services.ensure_fulfillment(deal)
    tomorrow = timezone.localdate() + datetime.timedelta(days=1)
    assert (
        crm_services.update_fulfillment_status(deal.id, manager, "SHIPPED", expected_delivery_date=tomorrow)[1] is None
    )
    later = tomorrow + datetime.timedelta(days=3)
    assert (
        crm_services.update_fulfillment_status(deal.id, manager, "IN_TRANSIT", expected_delivery_date=later)[1] is None
    )
    assert crm_services.update_fulfillment_status(deal.id, manager, "DELIVERED")[1] is None
    # delivery.line_accepted / delivery.line_disputed — клиент по строкам поставки
    from crm.models import Fulfillment

    sync_delivery_lines(Fulfillment.objects.filter(deal=deal))
    lines = list(DeliveryLine.objects.filter(deal=deal).order_by("line_no"))
    assert len(lines) >= 2
    assert accept_delivery_line(lines[0].pk, contact)[1] is None
    assert dispute_delivery_line(lines[1].pk, contact, "Повреждена упаковка")[1] is None
    # invite.sent — приглашение в Cabinet
    assert invite_contact_to_portal(contact, channel="email")[1] is None
    # invite.requested — приглашение через Telegram: доставит бот CRM (D1-9)
    assert invite_contact_to_portal(contact, channel="telegram")[1] is None
    # deal.lost — закрытие сделки без продажи
    lost_deal = Deal.objects.create(
        title="Проиграна", company=company, client=buyer_user, stage=DealStage.objects.get(code="CALCULATING")
    )
    _move(lost_deal, manager, "CLOSED_LOST")
    # document.created(generated) — выпуск документа из шаблона
    kind, _ = DocumentTemplateKind.objects.get_or_create(code="INVOICE", defaults={"name": "Счёт"})
    template, _ = DocumentTemplate.objects.get_or_create(company=company, name="Счёт", defaults={"kind": kind})
    draft, _ = GeneratedDocumentStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    GeneratedDocumentStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выпущен"})
    document = GeneratedDocument.objects.create(
        company=company, deal=deal, template=template, status=draft, number="СЧ-1", title="Счёт на оплату"
    )
    from crm.services.generated_documents import issue_document

    document.company = company
    assert issue_document(document, manager)[1] is None

    published = bus_support.published()
    seen = {e["type"] for e in published}
    expected = {events.event_type_name(short) for short in events.VALID_EVENT_TYPES}
    assert seen == expected, f"не опубликованы: {sorted(expected - seen)}; лишние: {sorted(seen - expected)}"
    for envelope in published:
        bus_support.assert_matches_contract(
            envelope, secret_masked=envelope["type"].endswith("acceptance_code_requested.v1")
        )
        assert envelope["source"] == "rt://erp" and envelope["tenant"] == "railtech"
    assert Quote.objects.filter(deal=deal).exists()


def test_reissue_of_a_returned_act_publishes_act_issued_again(world, mapped_world):  # noqa: F811
    from crm.services.billing import reissue_act

    act = world["act"]
    Act.objects.filter(pk=act.pk).update(status=ActStatus.objects.get(code="DRAFT"), rejection_reason="Не те позиции")
    reissued, error = reissue_act(act.pk, world["seller_user"])
    assert error is None and reissued.status.code == "ISSUED"
    issued = bus_support.only("act.issued")
    bus_support.assert_matches_contract(issued)
    assert issued["data"]["payload"]["erp_act_id"] == act.pk and "reason" not in issued["data"]["payload"]


# ── Гигиена: ни одного `except Exception` вокруг публикации, ни сигналов, ни вебхуков ───────────────

BACKEND = Path(__file__).resolve().parents[2]


def _publisher_names() -> set[str]:
    """Имена публикаторов ERP (`events.publish_*`, `document_events.publish_*`) и обёртки `watch_document_issue`."""
    from integration.services import document_events

    names = {n for module in (events, document_events) for n in dir(module) if n.startswith("publish_")}
    return names | {"watch_document_issue", "publish"}  # publish — прямой `get_bus().publish`


def _python_sources():
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        if (
            "/tests/" in f"/{relative}"
            or "/migrations/" in f"/{relative}"
            or relative.endswith(("conftest.py", "test_x.py"))
        ):
            continue
        yield path, relative


def _publishes(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _publisher_names() and name != "watch_document_issue":
                return True
    return False


def test_no_broad_except_around_event_publication():
    """Функция, публикующая событие, не содержит `except Exception` / `except:` / `except BaseException`: ошибка публикации
    обязана откатить изменение, а не раствориться в журнале."""
    offenders = []
    for path, relative in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if not _publishes(func):
                continue
            for handler in [n for n in ast.walk(func) if isinstance(n, ast.ExceptHandler)]:
                kind = handler.type
                broad = kind is None or (isinstance(kind, ast.Name) and kind.id in ("Exception", "BaseException"))
                if broad:
                    offenders.append(f"{relative}:{handler.lineno} ({func.name})")
    assert not offenders, f"except Exception в функциях, которые публикуют события: {offenders}"


def test_no_signals_webhooks_or_old_journal_remain_in_the_erp():
    # Слова собраны из частей, чтобы простой grep по `apps/erp` не находил сам сторож.
    banned = (
        "CRM_WEBHOOK" + "_URL",
        "IntegrationWebhook" + "Event",
        "WebhookEvent" + "Status",
        "deliver_webhook" + "_event",
        "integration." + "signals",
        "integration.services." + "webhooks",
        "event_" + "contract",
        "ERP_EVENTS_CONTRACT" + "_MODE",
        "ERP_EVENTS_SCHEMA" + "_PATH",
        "events.schema" + ".json",
    )
    offenders = []
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        if relative.endswith("test_bus_publish.py") or "/migrations/" in f"/{relative}":
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{relative}: {word}" for word in banned if word in text]
    assert not offenders, offenders
    assert not (BACKEND / "integration" / "signals.py").exists()
    assert not (BACKEND / "integration" / "services" / "webhooks.py").exists()
    assert not (BACKEND / "integration" / "tasks.py").exists()


def test_every_publisher_runs_inside_an_atomic_block():
    """Сервис, публикующий событие, сам открывает транзакцию (`@transaction.atomic` / `with transaction.atomic()`) либо вызывается
    из такой функции: `NotInTransactionError` в бою — это 500 клиенту, а тесты внутри `django_db` его не видят."""
    undecorated = []
    names = _publisher_names()
    for path, relative in _python_sources():
        if relative.startswith("integration/services/event") or relative.startswith(
            "integration/services/document_events"
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            direct = [c for c in ast.walk(func) if isinstance(c, ast.Call) and _call_name(c) in names]
            if not direct:
                continue
            decorated = any("atomic" in ast.unparse(d) for d in func.decorator_list)
            with_atomic = any(
                isinstance(w, ast.With) and any("atomic" in ast.unparse(i.context_expr) for i in w.items)
                for w in ast.walk(func)
            )
            if not (decorated or with_atomic):
                undecorated.append(f"{relative}::{func.name}")
    # Вспомогательные функции вызываются из атомарных сервисов; их перечень — осознанный список.
    assert (
        set(undecorated) <= ATOMIC_BY_CALLER
    ), f"публикует вне @transaction.atomic: {sorted(set(undecorated) - ATOMIC_BY_CALLER)}"
    assert ATOMIC_BY_CALLER <= set(
        undecorated
    ), f"лишние записи в списке: {sorted(ATOMIC_BY_CALLER - set(undecorated))}"


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


#: Функции, которые сами не атомарны, но вызываются только из атомарных сервисов (проверено чтением вызывающих).
ATOMIC_BY_CALLER = {
    "crm/services/deals.py::_publish_stage_events",  # из transition_deal_stage (@atomic)
    "crm/services/deals.py::register_new_deal",  # из DealViewSet.perform_create (with atomic)
    "sales/services/delivery_lines.py::_publish_decision",  # из accept/dispute_delivery_line (@atomic)
    "portal/services/acceptance.py::_emit_code_event",  # из request_acceptance_code (with transaction.atomic)
    "integration/services/handoff.py::_create_request",  # из _handoff в transaction.atomic
}
