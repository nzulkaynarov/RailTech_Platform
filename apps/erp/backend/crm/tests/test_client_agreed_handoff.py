"""ПРАВДА-2: клиент нажал «Принять редакцию» в Кабинете — ход переходит к нам, и мы об этом узнаём.

Раньше уведомление шло только автору КП: нет автора — не узнавал никто, задача «Отметить подписанным» не появлялась
вовремя. Теперь о согласии узнают автор, ответственный по сделке и держатели `contract.sign`; строка проекта сразу
несёт и статус «Согласован клиентом» (из него Платформа строит задачу), и слово клиенту «Договор на подписании».
"""

import pytest
from parties.models import Contact

from crm.constants import ContractStatusCode as S
from crm.services import projects
from crm.services.contracts import sign_contract_by_client
from crm.tests.projects_world import contract_in, pw  # noqa: F401
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def _accept(pw):  # noqa: F811
    contact = Contact.objects.create(company=pw.client, name="Ш. Юсупов", can_act=True, email="y@client.test")
    contract = contract_in(pw, S.PENDING_CLIENT)
    _, error = sign_contract_by_client(contract.pk, portal_contact=contact)
    assert error is None
    return contract


def _recipients():
    return {
        n.user.email for n in Notification.objects.filter(event_code="contract.signed_client").select_related("user")
    }


def test_responsible_and_signers_learn_about_the_agreement_even_without_a_quote_author(pw):  # noqa: F811
    assert pw.quote.prepared_by_id is None  # автора КП нет — раньше это значило «не узнал никто»

    _accept(pw)

    assert _recipients() == {"manager@own.test", "director@own.test", "accountant@own.test"}
    assert "supply@own.test" not in _recipients()  # права подписи нет — шума нет


def test_signers_are_told_even_when_the_deal_has_no_responsible_at_all(pw):  # noqa: F811
    pw.deal.manager = None
    pw.deal.save(update_fields=["manager"])

    _accept(pw)

    assert _recipients() == {"director@own.test", "accountant@own.test"}


def test_project_row_carries_the_next_step_right_after_the_agreement(pw):  # noqa: F811
    contract = _accept(pw)

    rows, _ = projects.list_projects(pw.admin, projects.Filters(deal_id=pw.deal.pk), limit=5, offset=0, ordering="")

    row = rows[0]
    assert row["documents"]["contract"]["status"] == "client_agreed"  # из него Платформа строит «Отметить подписанным»
    assert row["client_status"] == "contract_signing"  # слово клиенту — не «Согласуйте редакцию»
    assert row["documents"]["contract"]["number"] == contract.number
