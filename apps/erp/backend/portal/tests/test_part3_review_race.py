"""PART-3: два сотрудника решают одну карточку одновременно — «опубликовать» и «вернуть» — реальные соединения Postgres.

Первый (публикация) держит блокировку строки карточки, пока второй (возврат) уже пришёл: окно между «прочитал статус»
и «записал решение» растянуто паузой. Без `select_for_update` в `catalog.desk.items.set_published` оба видят «на проверке» и
оба получают 200: возврат записан, а публикация перезаписала его. С блокировкой второй ждёт коммита первого, видит
«опубликована» и получает 409 `PRODUCT_NOT_ON_REVIEW`. Мутационная проверка — в описании PR (ORCHESTRATOR §4.1): без блокировки
тест краснеет.
"""

from __future__ import annotations

import threading
import time

import pytest
from django.core import mail
from django.db import connection
from portal.tests.conftest import LOCMEM_BACKEND

from catalog import publishing
from catalog.desk import items
from catalog.models import Product, ProductReview
from catalog.tests.desk_world import make_staff

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)


def test_parallel_publish_and_return_give_exactly_one_decision(partner_world, monkeypatch, settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()
    staff = make_staff(partner_world["own"], "supply", label="race-supply")
    card = partner_world["cards"]["review"]
    card.hs_code = "8708301009"
    card.save()
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
    card.refresh_from_db()
    assert card.status.code == ("PUBLISHED" if wins == ["publish"] else "RETURNED")
    decided = list(
        ProductReview.objects.filter(product=card).exclude(decision="pending").values_list("decision", flat=True)
    )
    assert decided == ["published" if wins == ["publish"] else "returned"]
    assert not ProductReview.objects.filter(product=card, decision="pending").exists()
    assert len(mail.outbox) == 1  # партнёр получил одно письмо — о том решении, что победило
