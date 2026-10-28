"""D2-2: гонки склада и закупок — реальные параллельные соединения с Postgres (транзакционные тесты).

Каждый тест искусственно растягивает окно между «прочитал» и «записал» (`time.sleep` в нужном месте), чтобы без блокировки
гонка проявлялась всегда, а не «иногда». Мутационная проверка (ORCHESTRATOR §4.1, 2026-10-28) — в описании PR: без
`select_for_update` в соответствующем месте тест краснеет, с ним зелёный.

  * резерв: двум проектам нельзя отдать один остаток (`stock.lock_products`);
  * приёмка: одну строку заказа не принять дважды сверх количества (`_order_or_404(lock=True)` + строки под блокировкой);
  * «Отправить»: двойной клик — одно письмо и один переход (`_order_or_404(lock=True)`);
  * номер ЗП: параллельные создатели получают разные NNN без пропусков (`stock.next_number`).
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import connection
from django.utils import timezone
from inventory.services import stock
from inventory.tests.support import SUPPLY, api
from supply.models import SupplierOrder

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductStatus
from crm.models import CalcLine, Deal, DealStage, Quote, QuoteItem, QuoteStatus

pytestmark = pytest.mark.django_db(transaction=True)

STOCK = "/api/v1/stock/"


@pytest.fixture(autouse=True)
def locmem_mail(settings):
    channel = {
        "backend": "django.core.mail.backends.locmem.EmailBackend",
        "host": "",
        "port": 25,
        "username": "",
        "password": "",
        "use_tls": False,
        "from_email": "erp@demo.example",
    }
    settings.EMAIL_CHANNELS = {name: dict(channel) for name in ("transactional", "marketing", "system")}
    mail.outbox.clear()


@pytest.fixture
def lab():
    """Мир теста сам заводит нужные справочники: транзакционный тест после себя очищает таблицы, миграционным данным
    полагаться не на что."""
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    for code in ("CALCULATING", "CLOSED_LOST"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "APPROVED"):
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[
        0
    ]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})[0]
    seller = Company.objects.create(name="ООО Демо Рейл", inn="7700000401")
    seller.types.add(supplier_type)
    vendor = Company.objects.create(name="ООО Вымышленный Поставщик", inn="7700000402", email="sales@vendor.example")
    vendor.types.add(supplier_type)
    client = Company.objects.create(name="ООО Пример Логистик", inn="6600000401")
    client.types.add(client_type)
    role = CompanyRole.objects.create(company=seller, name="Снабжение", permissions=list(SUPPLY))
    user = CustomUser.objects.create_user(
        email="supply@lab.test", username="supply@lab.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=user,
        company=seller,
        role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "MEMBER", "sort_order": 10})[0],
        company_roles=[role],
        is_primary=True,
        is_active=True,
    )
    product = Product.objects.create(name="Перевод стрелочный Р65 1/11", manufacturer_part_number="СП-Р65-11")
    return {"seller": seller, "vendor": vendor, "client": client, "supply": user, "product": product}


def _deal_item(lab, quantity):
    deal = Deal.objects.create(title="Заявка", company=lab["client"], stage=DealStage.objects.get(code="CALCULATING"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        prepared_by=lab["supply"],
        status=QuoteStatus.objects.get(code="DRAFT"),
        seller_company=lab["seller"],
    )
    item = QuoteItem(
        quote=quote,
        position=1,
        product=lab["product"],
        imported_raw_name="Перевод",
        quantity=quantity,
        frozen_base_price=Decimal("1"),
    )
    item.save(skip_recalculate=True)
    CalcLine.objects.create(item=item)
    return deal, item


def _parallel(calls):
    """Запустить вызовы одновременно (барьер) и вернуть их результаты по порядку."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        try:
            barrier.wait()
            results[index] = call()
        except Exception as exc:  # noqa: BLE001 — результат теста: исключение тоже ответ
            results[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def _slow(monkeypatch, target, name, seconds=0.5):
    """Обёртка, которая после обычной работы функции ждёт: окно между чтением и записью растянуто."""
    original = getattr(target, name)

    def wrapper(*args, **kwargs):
        value = original(*args, **kwargs)
        time.sleep(seconds)
        return value

    monkeypatch.setattr(target, name, wrapper)


def test_two_projects_cannot_reserve_the_same_stock(lab, monkeypatch):
    stock.adjust(lab["supply"], lab["product"].pk, 5, cell="A-01")
    (deal_a, item_a), (deal_b, item_b) = _deal_item(lab, 3), _deal_item(lab, 3)
    _slow(monkeypatch, stock, "availability")  # прочитал свободный остаток — и думает, пока второй тоже читает

    results = _parallel(
        [
            lambda: api(lab["supply"])
            .post(
                f"{STOCK}reservations/",
                {"deal_id": deal_a.pk, "quote_item_id": item_a.pk, "quantity": 3},
                format="json",
            )
            .status_code,
            lambda: api(lab["supply"])
            .post(
                f"{STOCK}reservations/",
                {"deal_id": deal_b.pk, "quote_item_id": item_b.pk, "quantity": 3},
                format="json",
            )
            .status_code,
        ]
    )
    assert sorted(results) == [201, 409], results
    reserved = sum(r.quantity for r in stock.active_reservations())
    assert reserved == 3 <= 5, "резервов не больше остатка"


def test_a_line_cannot_be_received_twice_beyond_its_quantity(lab, monkeypatch):
    order = (
        api(lab["supply"])
        .post(
            f"{STOCK}orders/",
            {"supplier_id": lab["vendor"].pk, "lines": [{"product_id": lab["product"].pk, "quantity": 5}]},
            format="json",
        )
        .json()
    )
    assert api(lab["supply"]).post(f"{STOCK}orders/{order['id']}/send/", {}, format="json").status_code == 200
    expected = (timezone.localdate() + timedelta(days=3)).isoformat()
    assert (
        api(lab["supply"])
        .post(f"{STOCK}orders/{order['id']}/confirm/", {"expected_date": expected}, format="json")
        .status_code
        == 200
    )
    line = order["lines"][0]["id"]
    _slow(
        monkeypatch, stock, "add_stock"
    )  # принял на склад — и ещё не отметил на строке, а второй уже проверяет остаток

    receive = (
        lambda: api(lab["supply"])
        .post(  # noqa: E731
            f"{STOCK}orders/{order['id']}/receipts/", {"lines": [{"order_line_id": line, "quantity": 4}]}, format="json"
        )
        .status_code
    )
    results = _parallel([receive, receive])
    assert sorted(results) == [200, 400], results
    from inventory.models import StockBalance

    assert StockBalance.objects.get(product=lab["product"]).on_hand == 4, "принято один раз"


def test_double_click_on_send_sends_one_mail_and_one_transition(lab, monkeypatch):
    order = (
        api(lab["supply"])
        .post(
            f"{STOCK}orders/",
            {"supplier_id": lab["vendor"].pk, "lines": [{"product_id": lab["product"].pk, "quantity": 1}]},
            format="json",
        )
        .json()
    )
    import notifications.emails as emails

    _slow(monkeypatch, emails, "send_templated_email")
    send = (
        lambda: api(lab["supply"]).post(f"{STOCK}orders/{order['id']}/send/", {}, format="json").status_code
    )  # noqa: E731
    results = _parallel([send, send])
    assert sorted(results) == [200, 409], results
    assert len(mail.outbox) == 1, "письмо поставщику ушло один раз"
    assert SupplierOrder.objects.get(pk=order["id"]).log.filter(kind="sent").count() == 1


def test_parallel_order_numbers_are_unique_and_gapless(lab):
    def create():
        response = api(lab["supply"]).post(
            f"{STOCK}orders/",
            {"supplier_id": lab["vendor"].pk, "lines": [{"product_id": lab["product"].pk, "quantity": 1}]},
            format="json",
        )
        return response.status_code, response.json().get("number")

    results = _parallel([create] * 6)
    assert all(code == 201 for code, _number in results), results
    year = timezone.localdate().year
    assert sorted(number for _code, number in results) == [f"ЗП-{year}-{n:03d}" for n in range(1, 7)]
