"""FX-4: гонки смены реквизитов на реальных соединениях Postgres.

Первая транзакция держит строку компании, вторая в это время приходит: без `select_for_update` в
`portal/services/bank_details_change.py` вторая не ждёт (`assert worker.is_alive()` падает), оба подтверждения применились бы и
журнал получил бы две записи. С блокировкой вторая ждёт коммита первой и видит итог. Мутационная проверка — в описании PR
(ORCHESTRATOR §4.1). Данные коммитятся вручную и удаляются в `finally`, как в `test_part3_review_race.py`.
"""

from __future__ import annotations

import threading

from django.db import connection, transaction
from parties.models import Company, CompanyType, Contact
from portal.models import BankDetailsChangeRequest, BankDetailsChangeStatus, PortalNotice, PortalSecurityEvent
from portal.services import bank_details_change as service

TAG = "race-fx4"


def _world() -> dict:
    client_type, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    company = Company.objects.create(name=f"{TAG} company", inn="400500600", bank_details="р/с 20208000000000001111")
    company.types.add(client_type)
    admin = Contact.objects.create(
        company=company, name=f"{TAG} admin", email=f"{TAG}@example.uz", is_admin=True, can_act=True
    )
    return {"company": company, "admin": admin}


def _cleanup(world: dict) -> None:
    company = world["company"]
    PortalNotice.objects.filter(company=company).delete()
    PortalSecurityEvent.objects.filter(company=company).delete()
    BankDetailsChangeRequest.objects.filter(company=company).delete()
    Contact.objects.filter(company=company).delete()
    company.delete()


def _in_thread(fn):
    results: list = []

    def run():
        try:
            results.append(fn())
        finally:
            connection.close()

    worker = threading.Thread(target=run)
    return worker, results


def _submit(world, value="р/с 20208000000000002222"):
    return service.submit(world["company"], world["admin"], value, ip="203.0.113.7", user_agent="ua")


def test_two_approvals_apply_once(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        world = _world()
        try:
            change = _submit(world)
            worker, results = _in_thread(lambda: service.approve(change.pk, actor=None))
            with transaction.atomic():
                first = service.approve(change.pk, actor=None)
                worker.start()
                worker.join(timeout=1.5)
                assert worker.is_alive(), "второе подтверждение не дождалось блокировки первого"
            worker.join(timeout=30)

            assert not worker.is_alive()
            assert first.status == BankDetailsChangeStatus.APPROVED
            assert results[0].status == BankDetailsChangeStatus.APPROVED
            world["company"].refresh_from_db()
            assert world["company"].bank_details == "р/с 20208000000000002222"
            assert PortalSecurityEvent.objects.filter(company=world["company"], event_type="bank_details_changed").count() == 1
            assert PortalNotice.objects.filter(company=world["company"], kind="bank_requisites_changed").count() == 1
        finally:
            _cleanup(world)
            connection.close()


def test_two_submissions_give_one_pending_request(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        world = _world()
        try:
            worker, results = _in_thread(lambda: _outcome(world, "р/с 20208000000000003333"))
            with transaction.atomic():
                _submit(world)
                worker.start()
                worker.join(timeout=1.5)
                assert worker.is_alive(), "вторая подача не дождалась блокировки компании"
            worker.join(timeout=30)

            assert results == ["refused"]
            assert BankDetailsChangeRequest.objects.filter(
                company=world["company"], status=BankDetailsChangeStatus.PENDING
            ).count() == 1
        finally:
            _cleanup(world)
            connection.close()


def _outcome(world, value):
    from portal.exceptions import PortalConflict

    try:
        _submit(world, value)
        return "accepted"
    except PortalConflict:
        return "refused"
