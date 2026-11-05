"""PART-3: два сотрудника решают одну карточку одновременно — «опубликовать» и «вернуть» — реальные соединения Postgres.

Первый (публикация) держит блокировку строки карточки, пока второй (возврат) уже пришёл: окно между «прочитал статус»
и «записал решение» растянуто паузой. Без `select_for_update` в `catalog.desk.items.set_published` оба видят «на проверке» и
оба получают 200: возврат записан, а публикация перезаписала его. С блокировкой второй ждёт коммита первого, видит
«опубликована» и получает 409 `PRODUCT_NOT_ON_REVIEW`. Мутационная проверка — в описании PR (ORCHESTRATOR §4.1): без блокировки
тест краснеет.

Данные коммитятся вручную (`django_db_blocker`) и удаляются в `finally`, а не `transaction=True`: сброс всей базы после такого
теста стирал бы справочники миграций у следующих тестов того же воркера.
"""

from __future__ import annotations

import threading
import time

from django.core import mail
from django.db import connection
from parties.models import Company, CompanyRelationship, Contact
from portal.tests.conftest import LOCMEM_BACKEND
from portal.tests.partner_world import make_card, make_partner, status_row

from accounts.models import CustomUser
from accounts.testing import make_own_company
from catalog import publishing
from catalog.desk import items
from catalog.models import Category, Product, ProductReview, ProductStatus
from core.models import UnitOfMeasure
from crm.models import ActivityLog
from notifications.models import EmailLog

TAG = "race-part3"


def test_parallel_publish_and_return_give_exactly_one_decision(
    django_db_setup, django_db_blocker, monkeypatch, settings
):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()
    with django_db_blocker.unblock():
        created = _build(settings)
        try:
            _run(created, monkeypatch)
        finally:
            _cleanup(created)
            connection.close()


def _build(settings) -> dict:
    for code in ("DRAFT", "REVIEW", "RETURNED", "PUBLISHED"):
        status_row(code)
    own = make_own_company(Company.objects.create(name=f"{TAG} own", inn="410000001"))
    settings.OWN_COMPANY_ID = own.pk
    staff = CustomUser.objects.create_user(email=f"{TAG}@staff.example", username=TAG, password="x", is_superuser=True)
    partner, contact = make_partner(f"{TAG} partner", "410000002", f"{TAG}@partner.example")
    unit = UnitOfMeasure.objects.get_or_create(code="796", defaults={"name": "шт"})[0]
    category = Category.objects.create(name=f"{TAG} category")
    card = make_card(
        f"{TAG} card",
        "REVIEW",
        source=partner,
        owner=own,
        mpn=f"{TAG}-1",
        uom=unit,
        category=category,
        hs_code="8708301009",
    )
    ProductReview.objects.create(product=card, submitted_by_contact=contact)
    return {"own": own, "staff": staff, "partner": partner, "contact": contact, "card": card, "category": category}


def _cleanup(created: dict) -> None:
    card = created["card"]
    ActivityLog.objects.filter(entity_id=card.pk, event_code__startswith="admin.product_review").delete()
    EmailLog.objects.filter(to_emails__contains=[created["contact"].email]).delete()
    ProductReview.objects.filter(product=card).delete()
    Product.objects.filter(pk=card.pk).delete()
    created["category"].delete()
    CompanyRelationship.objects.filter(company=created["partner"]).delete()
    Contact.objects.filter(company=created["partner"]).delete()
    created["partner"].delete()
    created["staff"].delete()
    created["own"].delete()


def _run(created: dict, monkeypatch) -> None:
    staff, card = created["staff"], created["card"]
    seen_by_publisher = Product.objects.select_related("status", "source_supplier").get(pk=card.pk)

    original = publishing.publish_product
    inside = threading.Event()

    def slow_publish(product, actor):
        if not inside.is_set():
            inside.set()
            time.sleep(
                1.5
            )  # публикующий держит строку: второй либо ждёт (блокировка), либо читает «на проверке» (гонка)
        return original(product, actor)

    monkeypatch.setattr(publishing, "publish_product", slow_publish)
    results: dict = {}

    def publish():
        try:
            results["publish"] = items.set_published(seen_by_publisher, True, staff)
        except items.ItemError as error:
            results["publish"] = error
        finally:
            connection.close()

    def give_back():
        try:
            results["return"] = items.return_item(card.pk, {"reason": "Вернуть"}, staff)
        except items.ItemError as error:
            results["return"] = error
        finally:
            connection.close()

    first = threading.Thread(target=publish)
    second = threading.Thread(target=give_back)
    first.start()
    assert inside.wait(5)
    second.start()
    first.join(15)
    second.join(15)

    wins = [name for name, result in results.items() if isinstance(result, Product)]
    refused = [result for result in results.values() if isinstance(result, items.ItemError)]
    assert len(wins) == 1, results
    assert len(refused) == 1 and refused[0].code == "PRODUCT_NOT_ON_REVIEW", results
    won = "published" if wins == ["publish"] else "returned"
    card.refresh_from_db()
    assert card.status.code == won.upper()
    decided = list(
        ProductReview.objects.filter(product=card).exclude(decision="pending").values_list("decision", flat=True)
    )
    assert decided == [won]
    assert not ProductReview.objects.filter(product=card, decision="pending").exists()
    assert len(mail.outbox) == 1  # партнёр получил одно письмо — о том решении, что победило
    assert ProductStatus.objects.filter(code=won.upper()).exists()
