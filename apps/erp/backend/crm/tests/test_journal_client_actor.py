"""СЦ-8 (2): история документов называет клиента, а не «систему»; выпуск акта и приёмка клиентом пишутся в журнал.

Факт, из которого выводится подпись «кто»: контакт клиента, сделавший действие в кабинете (`ActivityLog.contact` и
`contact_name` в параметрах), либо сотрудник. Раньше у строк клиента `user=None`, и карточка проекта показывала «система».
"""

import pytest
from integration.tests import world as w
from parties.models import Contact

from core.models import Notification
from crm.constants import ContractStatusCode as S
from crm.constants import InvoiceStatusCode
from crm.models import ActivityLog
from crm.services import billing, projects
from crm.services.contracts import sign_contract_by_client
from crm.tests.projects_world import contract_in, pw  # noqa: F401
from crm.tests.test_act_flow import _act

pytestmark = pytest.mark.django_db


def _contact(pw):  # noqa: F811
    return Contact.objects.create(company=pw.client, name="Каримов Алишер", can_act=True, language="ru")


def _journal(pw):  # noqa: F811
    deal = projects.project_queryset().get(pk=pw.deal.pk)
    return projects._journal(deal)


def test_contract_agreed_in_the_cabinet_names_the_contact_not_the_system(pw):  # noqa: F811
    contact = _contact(pw)
    contract = contract_in(pw, S.PENDING_CLIENT)
    assert sign_contract_by_client(contract.id, portal_contact=contact)[1] is None

    rows = [row for row in _journal(pw) if row["code"] == "contract.client_agreed"]
    assert len(rows) == 1
    assert rows[0]["actor_name"] == "Каримов Алишер"
    assert rows[0]["text"] == "Редакция договора согласована клиентом"


def test_act_accepted_and_returned_in_the_cabinet_name_the_contact(pw):  # noqa: F811
    contact = _contact(pw)
    act = _act(pw)
    assert billing.sign_act(act.id, portal_contact=contact)[1] is None
    assert {r["code"]: r["actor_name"] for r in _journal(pw)}["act.signed"] == "Каримов Алишер"

    act2 = _act(pw)
    assert billing.reject_act(act2.id, None, "Не совпадает сумма", portal_contact=contact)[1] is None
    assert {r["code"]: r["actor_name"] for r in _journal(pw)}["act.rejected"] == "Каримов Алишер"


def test_old_rows_without_contact_name_are_resolved_by_contact_id(pw):  # noqa: F811
    """Строки, записанные до правки (только `contact_id` в параметрах), тоже показывают имя без переноса данных."""
    contact = _contact(pw)
    ActivityLog.objects.create(
        action="Акт принят заказчиком",
        event_code="act.signed",
        event_params={"number": "А-1", "channel": "portal", "contact_id": contact.pk},
        deal=pw.deal,
    )
    row = [r for r in _journal(pw) if r["code"] == "act.signed"][0]
    assert row["actor_name"] == "Каримов Алишер"


def test_staff_action_still_names_the_employee_and_no_actor_stays_empty(pw):  # noqa: F811
    ActivityLog.objects.create(action="Акт выпущен", event_code="act.issued", user=pw.accountant, deal=pw.deal)
    ActivityLog.objects.create(action="Проект выполнен", event_code="project.done", deal=pw.deal)
    names = {r["code"]: r["actor_name"] for r in _journal(pw)}
    assert names["act.issued"] == pw.accountant.email and names["project.done"] is None


def test_issuing_an_act_writes_a_journal_row_with_the_issuer(pw):  # noqa: F811
    contract = w.add_contract(pw.deal, pw.quote, S.SIGNED)
    invoice = w.add_invoice(pw.deal, InvoiceStatusCode.PAID, total="5", paid="5", contract=contract)
    from crm.tests.delivery_support import mark_delivered

    mark_delivered(pw.deal)
    act, error = billing.generate_act(invoice.id, pw.accountant)
    assert error is None, error
    entry = ActivityLog.objects.get(event_code="act.issued", deal=pw.deal)
    assert (
        entry.user_id == pw.accountant.pk and entry.entity_id == act.id and entry.event_params["number"] == act.number
    )
    assert [r["code"] for r in _journal(pw) if r["code"] == "act.issued"] == ["act.issued"]


def test_bell_text_on_cabinet_acceptance_says_accepted_by_the_client_not_signed(  # noqa: F811
    pw, django_capture_on_commit_callbacks  # noqa: F811
):
    contact = _contact(pw)
    act = _act(pw)
    with django_capture_on_commit_callbacks(execute=True):
        assert billing.sign_act(act.id, portal_contact=contact)[1] is None
    note = Notification.objects.filter(event_code="act.signed").order_by("-id").first()
    assert note is not None
    assert "принят клиентом" in note.message and "подписан" not in note.message.lower()
    assert "подписан" not in note.title.lower()
