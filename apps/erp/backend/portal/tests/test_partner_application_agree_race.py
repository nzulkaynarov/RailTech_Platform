"""Согласование договора и отклонение заявки в один момент (FX-1): согласие не воскрешает отклонённую заявку.

Отклонение держит строку заявки в открытой транзакции, параллельный запрос согласования обязан дождаться её и увидеть
статус `rejected`. Без `select_for_update` в согласовании запрос читает прежний `contract_sent`, ждёт только на записи и
затирает отклонение — тест краснеет.
"""

import threading

import pytest
from django.conf import settings as dj_settings
from django.db import connection, transaction
from parties.models import PartnerApplication, PartnerApplicationSource, PartnerApplicationStatus
from portal.tests.conftest import PortalAPIClient, make_portal_session

pytestmark = pytest.mark.django_db(transaction=True)

AGREE = "/api/portal/v1/company/partner-application/agree"


def test_agree_waits_for_concurrent_reject(client_company, client_contact):
    app = PartnerApplication.objects.create(
        source=PartnerApplicationSource.CLIENT_CABINET,
        company=client_company,
        applicant_contact=client_contact,
        company_name=client_company.name,
        kind="supplier",
        categories_description="Поставка стрелочных переводов",
        status=PartnerApplicationStatus.CONTRACT_SENT,
        contract_number="PRT-RACE-1",
        contact_name="Кандидат",
        email=client_contact.email,
    )
    session = make_portal_session(client_contact, client_company, "magic_link")
    responses = []

    def agree():
        client = PortalAPIClient()
        client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
        client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
        try:
            responses.append(client.post(AGREE, {"notes": ""}, format="json"))
        finally:
            connection.close()

    worker = threading.Thread(target=agree)
    with transaction.atomic():
        locked = PartnerApplication.objects.select_for_update().get(pk=app.pk)
        locked.status = PartnerApplicationStatus.REJECTED
        locked.rejected_reason = "Отклонена сотрудником"
        locked.save(update_fields=["status", "rejected_reason"])
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive(), "согласование не дождалось транзакции отклонения"
    worker.join(timeout=30)

    assert not worker.is_alive()
    app.refresh_from_db()
    assert app.status == PartnerApplicationStatus.REJECTED
    assert app.candidate_agreed_at is None
    assert responses[0].status_code == 400
    assert responses[0].json()["detail"] == "NOT_IN_CONTRACT_SENT_STATUS"
