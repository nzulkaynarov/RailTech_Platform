"""FX-6: гонка «двое администраторов снимают друг друга» на реальных соединениях Postgres.

Первая транзакция держит блокировку компании, вторая в это время приходит: без `lock_company_row` в
`portal/services/team.py` вторая не ждёт (`assert worker.is_alive()` падает) и оба видят «другой администратор остался».
Мутационная проверка — в описании PR (ORCHESTRATOR §4.1).
"""

from __future__ import annotations

import threading

from django.db import connection, transaction
from parties.models import Company, CompanyType, Contact, active_contact_q
from portal.exceptions import PortalValidationError
from portal.services import team

TAG = "race-fx6"


def _world():
    client_type, _ = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    company = Company.objects.create(name=f"{TAG} company", inn="700800900")
    company.types.add(client_type)
    first = Contact.objects.create(
        company=company,
        name="A",
        email=f"a-{TAG}@example.uz",
        is_admin=True,
        can_act=True,
    )
    second = Contact.objects.create(
        company=company,
        name="B",
        email=f"b-{TAG}@example.uz",
        is_admin=True,
        can_act=True,
    )
    return {"company": company, "a": first, "b": second}


def _cleanup(world):
    Contact.objects.filter(company=world["company"]).delete()
    world["company"].delete()


def test_two_admins_cannot_demote_each_other(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        world = _world()
        try:
            results: list = []

            def second_demotion():
                try:
                    team.update_member_rights(world["company"], world["a"].pk, {"is_admin": False})
                    results.append("applied")
                except PortalValidationError as error:
                    results.append(str(error.detail))
                finally:
                    connection.close()

            worker = threading.Thread(target=second_demotion)
            with transaction.atomic():
                team.update_member_rights(world["company"], world["b"].pk, {"is_admin": False})
                worker.start()
                worker.join(timeout=1.5)
                assert worker.is_alive(), "вторая смена прав не дождалась блокировки компании"
            worker.join(timeout=30)

            assert not worker.is_alive()
            assert results == ["LAST_ADMIN_CANNOT_BE_REMOVED"]
            assert Contact.objects.filter(active_contact_q(), company=world["company"], is_admin=True).count() == 1
        finally:
            _cleanup(world)
            connection.close()
