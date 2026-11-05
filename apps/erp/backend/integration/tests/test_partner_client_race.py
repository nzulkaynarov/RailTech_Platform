"""PART-CRM: заявка партнёра в момент ответа CRM не теряется — реальные соединения Postgres.

Заявка проверяет сопоставление клиента CRM (его нет — событие откладывается), и пока она не записала отложенное событие,
приходит ответ CRM `linked`: он сопоставляет компанию и публикует отложенные — а этой заявки среди них ещё нет. Окно растянуто
паузой у заявки после проверки: без общей блокировки по компании (`partner_client.lock_if_partner`) ответ успевает полностью, а
заявка после него записывает отложенное событие, которое уже некому опубликовать. С блокировкой ответ ждёт коммита заявки и
публикует её. Мутационная проверка — в описании PR (ORCHESTRATOR §4.1): без `lock_if_partner` тест краснеет.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connection
from integration.models import CrmClientMapping, DeferredRequestEvent, PartnerCrmLink
from integration.services import events, partner_client
from integration.tests import bus_support
from parties.models import Company, CompanyRelationship, CompanyType, Contact
from portal.services.requests import create_client_request

pytestmark = pytest.mark.django_db(transaction=True)


def test_a_partner_request_made_during_the_answer_is_published_once(monkeypatch):
    company = Company.objects.create(name="OOO Race Supplier", inn="300000999")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    CompanyRelationship.objects.create(
        company=company, role="partner", status="active", modules=["my_products", "catalog_requests"]
    )
    contact = Contact.objects.create(company=company, name="Race", email="race@supplier.example.uz", can_act=True)
    PartnerCrmLink.objects.create(company=company, status="requested")  # запрос отправлен: ответ `linked` принимается
    bus_support.reset()

    original = events.publish_request_created
    checked = threading.Event()
    answered = threading.Event()

    def slow(*args, **kwargs):
        event = original(*args, **kwargs)
        if threading.current_thread().name == "request" and not checked.is_set():
            checked.set()  # сопоставления нет — событие отложат; теперь пауза: ответ CRM успевает (или ждёт блокировку)
            answered.wait(1.5)
        return event

    monkeypatch.setattr(events, "publish_request_created", slow)
    failures: list[BaseException] = []

    def make_request():
        try:
            create_client_request(company, contact, summary="Нужен кабель", lines=[{"text": "Кабель"}], attachments=[])
        except BaseException as exc:  # noqa: BLE001 — тест собирает сбой потока
            failures.append(exc)
        finally:
            connection.close()

    def answer():
        try:
            assert checked.wait(5)
            partner_client.apply_client_resolved(
                {"erp_company_id": company.pk, "status": "linked", "crm_client_id": 77, "actor": {"type": "system"}}
            )
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)
        finally:
            answered.set()
            connection.close()

    first = threading.Thread(target=make_request, name="request")
    second = threading.Thread(target=answer, name="answer")
    first.start()
    second.start()
    first.join(15)
    second.join(15)

    assert failures == []
    assert CrmClientMapping.objects.get(company=company).crm_client_id == 77
    published = bus_support.published("request.created")
    assert len(published) == 1, "заявка потеряна: ответ CRM прошёл между проверкой и записью отложенного события"
    assert DeferredRequestEvent.objects.get().published_at is not None


def test_a_handoff_and_the_first_invite_by_tin_go_in_turn(monkeypatch, settings):
    """Передача клиента по ИНН и первое приглашение партнёра: обе берут блокировку по компании ДО проверки «партнёр ли она».

    Приглашение (отдельная транзакция) держит блокировку и паузой после отправки запроса растягивает окно: без общей
    блокировки передача не видит ещё не зафиксированное отношение партнёра и создаёт сопоставление; с блокировкой она ждёт
    коммита приглашения, видит партнёра и удерживается (409, сопоставления нет).
    """
    from integration.exceptions import IntegrationConflict
    from integration.services.handoff import process_client_handoff
    from integration.tests.test_handoff import payload
    from portal.desk import service as desk_service
    from portal.tests.conftest import LOCMEM_BACKEND

    from accounts.models import CustomUser

    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    company = Company.objects.create(name="OOO Race Two", inn="300000888")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    contact = Contact.objects.create(company=company, name="Race", email="race2@supplier.example.uz", can_act=True)
    staff = CustomUser.objects.create_user(email="race-staff@d2-3.test", username="race-staff", password="pw")
    bus_support.reset()

    original = desk_service.request_client_in_crm
    in_invite = threading.Event()
    handed_off = threading.Event()

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        in_invite.set()  # приглашение ещё не зафиксировано; пауза: передача успевает (или ждёт блокировку)
        handed_off.wait(1.5)
        return result

    monkeypatch.setattr(desk_service, "request_client_in_crm", slow)
    results: dict = {}

    def run_invite():
        try:
            desk_service.invite(company, contact.pk, staff)
        except BaseException as exc:  # noqa: BLE001
            results["invite"] = exc
        finally:
            connection.close()

    def run_handoff():
        try:
            assert in_invite.wait(5)
            process_client_handoff(
                payload(crm_client_id=4201, inn=company.inn, create_request=False, email="y@o.example.uz")
            )
            results["handoff"] = "created"
        except IntegrationConflict as exc:
            results["handoff"] = exc.detail
        except BaseException as exc:  # noqa: BLE001
            results["handoff"] = exc
        finally:
            handed_off.set()
            connection.close()

    first = threading.Thread(target=run_invite, name="invite")
    second = threading.Thread(target=run_handoff, name="handoff")
    first.start()
    second.start()
    first.join(15)
    second.join(15)

    assert "invite" not in results, results
    assert str(results["handoff"]) == "PARTNER_VERIFICATION_REQUIRED", results
    assert not CrmClientMapping.objects.exists(), "передача не создала сопоставление партнёру"
