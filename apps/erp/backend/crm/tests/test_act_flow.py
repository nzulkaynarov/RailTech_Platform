"""Акт: скан подписанного и возврат, записанные сотрудником (D2-5, SPEC-v3 §2.4 «Акт»).

Покрыто: «Выпущен» → «Подписан (скан)» и «Возвращён с причиной» → повторный выпуск; недопустимые переходы по всем статусам;
права `fulfillment.act` в домене (менеджер, снабженец, посторонний — 403); сигнатура и лимит скана; события шины
(`act.accepted`, `act.returned`) по схеме; журнал; проект «Выполнено» (акт подписан и счета оплачены) пишется один раз.
"""

import pytest
from django.utils import timezone
from integration.tests import bus_support
from integration.tests import world as w

from crm.constants import ActStatusCode as A
from crm.constants import ContractStatusCode, InvoiceStatusCode
from crm.models import ActivityLog
from crm.services import act_flow, projects
from crm.tests.projects_world import PDF, PNG, api, pw, scan  # noqa: F401

pytestmark = pytest.mark.django_db

ALL = [A.DRAFT, A.ISSUED, A.SIGNED, A.CANCELLED]


def _act(pw, status=A.ISSUED, invoice_status=InvoiceStatusCode.PAID, **fields):  # noqa: F811
    contract = w.add_contract(pw.deal, pw.quote, ContractStatusCode.SIGNED)
    invoice = w.add_invoice(
        pw.deal, invoice_status, total="5000000", paid="5000000" if invoice_status == "PAID" else "0", contract=contract
    )
    return w.add_act(pw.deal, status, contract=contract, invoice=invoice, **fields)


def _post(user, act, action, body=None, format="json"):
    return api(user).post(f"/api/v1/crm/acts/{act.id}/{action}/", body or {}, format=format)


def test_attach_scan_signs_the_issued_act(pw):  # noqa: F811
    act = _act(pw)
    response = _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart")
    assert response.status_code == 200, response.content
    act.refresh_from_db()
    assert act.status.code == A.SIGNED and act.signed_file and act.signed_at and act.acceptor_signed_at
    event = bus_support.only("act.accepted")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["erp_act_id"] == act.id and event["data"]["actor"]["type"] == "staff"
    entry = ActivityLog.objects.get(event_code="act.scan_attached")
    assert entry.user_id == pw.accountant.pk and entry.entity_type == "act" and entry.entity_id == act.id


def test_project_is_done_when_the_act_is_signed_and_invoices_are_paid(pw):  # noqa: F811
    act = _act(pw)
    pw.deal.refresh_from_db()
    assert not projects.project_is_done(pw.deal), "акт ещё не подписан"
    _post(pw.director, act, "attach-scan", {"file": scan("a.png", PNG, "image/png")}, "multipart")
    deal = projects.project_queryset().get(pk=pw.deal.pk)
    assert projects.project_is_done(deal) and projects.project_step(deal) == "DONE"
    assert projects.client_status(deal) == "done"
    assert ActivityLog.objects.filter(event_code="project.done", deal=deal).count() == 1


def test_project_is_not_done_while_an_invoice_is_unpaid(pw):  # noqa: F811
    act = _act(pw, invoice_status=InvoiceStatusCode.ISSUED)
    _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart")
    deal = projects.project_queryset().get(pk=pw.deal.pk)
    assert not projects.project_is_done(deal)
    assert not ActivityLog.objects.filter(event_code="project.done").exists()


def _done_entries(deal):
    return ActivityLog.objects.filter(event_code="project.done", deal=deal).count()


def _pay(pw, invoice):  # noqa: F811
    from decimal import Decimal

    from crm.services.billing import record_payment

    return record_payment(
        invoice.id, actor=pw.admin, amount=Decimal("5000000"), reference="p-1", paid_at=timezone.now().date()
    )


def test_done_when_the_payment_comes_after_the_signed_scan(pw):  # noqa: F811
    """Порядок «скан акта → оплата»: последним условием оказывается оплата — запись `project.done` пишет она."""
    act = _act(pw, invoice_status=InvoiceStatusCode.ISSUED)
    _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart")
    assert _done_entries(pw.deal) == 0
    payment, error = _pay(pw, act.invoice)
    assert error is None, error
    deal = projects.project_queryset().get(pk=pw.deal.pk)
    assert projects.project_is_done(deal) and projects.project_step(deal) == "DONE"
    assert _done_entries(deal) == 1


def test_done_when_the_scan_comes_after_the_payment(pw):  # noqa: F811
    """Порядок «оплата → скан акта»: последним оказывается скан."""
    act = _act(pw, invoice_status=InvoiceStatusCode.ISSUED)
    _, error = _pay(pw, act.invoice)
    assert error is None, error
    assert _done_entries(pw.deal) == 0
    _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart")
    assert _done_entries(pw.deal) == 1


def test_project_done_is_logged_once_however_often_it_is_checked(pw):  # noqa: F811
    act = _act(pw, invoice_status=InvoiceStatusCode.ISSUED)
    _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart")
    _pay(pw, act.invoice)
    assert _done_entries(pw.deal) == 1
    assert projects.log_project_done_once(pw.deal, pw.accountant) is False
    assert _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart").status_code == 409
    assert _pay(pw, act.invoice)[1] is None  # повтор той же оплаты — прежний платёж, не новая запись
    assert _done_entries(pw.deal) == 1


def test_done_when_the_customer_accepts_the_act_in_the_portal(pw):  # noqa: F811
    """Приёмка акта заказчиком в портале (`billing.sign_act`) — третий путь к «Выполнено»; счёт уже оплачен."""
    from parties.models import Contact

    from crm.services.billing import sign_act

    act = _act(pw)
    contact = Contact.objects.create(company=pw.client, name="Контакт клиента", can_act=True, language="ru")
    signed, error = sign_act(act.id, portal_contact=contact)
    assert error is None, error
    assert signed.status.code == A.SIGNED
    assert _done_entries(pw.deal) == 1
    assert projects.log_project_done_once(pw.deal) is False


def test_portal_acceptance_while_an_invoice_is_unpaid_does_not_close_the_project(pw):  # noqa: F811
    from parties.models import Contact

    from crm.services.billing import sign_act

    act = _act(pw, invoice_status=InvoiceStatusCode.ISSUED)
    contact = Contact.objects.create(company=pw.client, name="Контакт клиента", can_act=True, language="ru")
    assert sign_act(act.id, portal_contact=contact)[1] is None
    assert _done_entries(pw.deal) == 0
    _pay(pw, act.invoice)
    assert _done_entries(pw.deal) == 1


@pytest.mark.parametrize("status", [s for s in ALL if s != A.ISSUED])
def test_scan_and_return_only_from_issued(pw, status):  # noqa: F811
    act = _act(pw, status)
    assert _post(pw.accountant, act, "attach-scan", {"file": scan()}, "multipart").status_code == 409
    assert _post(pw.accountant, act, "record-return", {"reason": "Ошибка в сумме"}).status_code == 409
    act.refresh_from_db()
    assert act.status.code == status and not act.signed_file
    assert not bus_support.published("act.accepted") and not bus_support.published("act.returned")


def test_record_return_goes_back_to_draft_with_the_reason(pw):  # noqa: F811
    act = _act(pw)
    assert _post(pw.accountant, act, "record-return", {}).json() == {"detail": "REASON_REQUIRED"}
    assert _post(pw.accountant, act, "record-return", {"reason": " "}).status_code == 400
    response = _post(pw.accountant, act, "record-return", {"reason": "Неверная сумма в акте"})
    assert response.status_code == 200, response.content
    act.refresh_from_db()
    assert act.status.code == A.DRAFT and act.rejection_reason == "Неверная сумма в акте"
    assert projects.act_word(act) == "returned"
    event = bus_support.only("act.returned")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["reason"] == "Неверная сумма в акте"
    entry = ActivityLog.objects.get(event_code="act.rejected")
    assert entry.user_id == pw.accountant.pk and entry.reason == "Неверная сумма в акте" and entry.entity_id == act.id
    assert act_flow.allowed_actions(act, pw.accountant) == ["reissue"]


@pytest.mark.parametrize(
    ("name", "content", "content_type", "ok"),
    [
        ("scan.pdf", PDF, "application/pdf", True),
        ("scan.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8, "image/webp", True),
        ("fake.pdf", b"not a pdf at all", "application/pdf", False),
        ("scan.docx", b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
        ("scan.pdf", PDF, "application/zip", False),
        ("empty.png", b"", "image/png", False),
    ],
)
def test_act_scan_validation(pw, name, content, content_type, ok):  # noqa: F811
    act = _act(pw)
    response = _post(pw.accountant, act, "attach-scan", {"file": scan(name, content, content_type)}, "multipart")
    act.refresh_from_db()
    if ok:
        assert response.status_code == 200 and act.status.code == A.SIGNED
    else:
        assert response.status_code == 400 and act.status.code == A.ISSUED and not act.signed_file
        assert not bus_support.published("act.accepted")


@pytest.mark.parametrize("who", ["manager", "supply", "outsider", "stranger"])
def test_act_actions_need_the_right_in_the_domain(pw, who):  # noqa: F811
    act = _act(pw)
    user = getattr(pw, who)
    assert _post(user, act, "attach-scan", {"file": scan()}, "multipart").status_code == 403
    assert _post(user, act, "record-return", {"reason": "x"}).status_code == 403
    act.refresh_from_db()
    assert act.status.code == A.ISSUED and not act.signed_file
    assert bus_support.published() == []


def test_service_rechecks_the_right_and_the_object(pw):  # noqa: F811
    act = _act(pw)
    assert act_flow.attach_act_scan(act.id, pw.manager, scan()) == (None, "MEMBER_REQUIRED_FOR_ACTION")
    assert act_flow.record_act_return(act.id, pw.supply, "x") == (None, "MEMBER_REQUIRED_FOR_ACTION")
    signed, error = act_flow.attach_act_scan(act.id, pw.director, scan())
    assert error is None and signed.status.code == A.SIGNED
    assert act_flow.attach_act_scan(act.id, pw.director, scan()) == (
        None,
        "ACT_SIGN_NOT_ALLOWED",
    ), "повторно скан не прикрепить"


def test_outsider_cannot_even_see_the_act(pw):  # noqa: F811
    act = _act(pw)
    assert api(pw.stranger).get(f"/api/v1/crm/acts/{act.id}/").status_code in (403, 404)


def test_reissue_after_return_keeps_the_same_document(pw):  # noqa: F811
    act = _act(pw)
    _post(pw.accountant, act, "record-return", {"reason": "Опечатка"})
    response = _post(pw.accountant, act, "reissue")
    assert response.status_code == 200, response.content
    act.refresh_from_db()
    assert act.status.code == A.ISSUED
