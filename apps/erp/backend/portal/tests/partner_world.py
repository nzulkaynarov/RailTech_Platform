"""Мир «Мои товары» партнёра (PART-2): два партнёра, их карточки и цены, сотрудник с правом публикации. Названия выдуманы.

Нужен тестам `test_partner_products*.py` и сторожу контракта: карточки во всех статусах глазами партнёра А, чужие карточки и
чужие цены, из которых в ответе А не должно быть ничего.
"""

import base64
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
import pytest
from django.conf import settings as dj_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from parties.models import Company, CompanyRelationship, CompanyType, Contact, RelationshipRole, RelationshipStatus
from portal.services.roles import ROLE_DEFAULT_MODULES

from catalog.models import Category, Manufacturer, Product, ProductReview, ProductStatus, SupplierOffer
from master_data.models import Currency, UnitOfMeasure
from sourcing.catalog_import import run_catalog_import

PREFIX = "/api/portal/v1/partner"
URL = f"{PREFIX}/price-list"


def status_row(code: str) -> ProductStatus:
    names = {"DRAFT": "Черновик", "REVIEW": "На проверке", "RETURNED": "Возвращена", "PUBLISHED": "Опубликован"}
    return ProductStatus.objects.get_or_create(code=code, defaults={"name": names[code]})[0]


def make_partner(name: str, inn: str, email: str, *, responsible=None, can_act=True):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    contact = Contact.objects.create(
        company=company, name=f"Контакт {name}", email=email, can_act=can_act, language="ru"
    )
    CompanyRelationship.objects.create(
        company=company,
        role=RelationshipRole.PARTNER,
        status=RelationshipStatus.ACTIVE,
        modules=list(ROLE_DEFAULT_MODULES["partner"]),
        responsible=responsible,
    )
    return company, contact


def client_for(contact):
    # Импорт здесь: `conftest` сам подключает этот модуль (фикстура `partner_world`) — на уровне модуля вышел бы цикл
    from portal.tests.conftest import PortalAPIClient, make_portal_session

    session = make_portal_session(contact, contact.company, "magic_link")
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


def make_card(name: str, status: str, *, source=None, owner=None, mpn="", brand=None, category=None, **extra):
    return Product.objects.create(
        name=name,
        status=status_row(status),
        source_supplier=source,
        owner_company=owner,
        manufacturer_part_number=mpn,
        brand=brand,
        category=category,
        **extra,
    )


def make_offer(product, supplier, price="100.00", currency="USD", **extra):
    code = Currency.objects.get_or_create(code=currency, defaults={"name": currency})[0]
    return SupplierOffer.objects.create(
        product=product, supplier=supplier, base_price=Decimal(price), currency=code, **extra
    )


@pytest.fixture
def partner_world(db, seller_company, settings):
    from accounts.models import CompanyMember, CustomUser, WorkspaceRole

    settings.OWN_COMPANY_ID = seller_company.pk

    uom = UnitOfMeasure.objects.get_or_create(code="796", defaults={"name": "шт"})[0]
    category = Category.objects.create(name="Крепёж для испытаний")
    brand = Manufacturer.objects.create(name="Аквилон")
    a, a_contact = make_partner("Завод Север", "300000111", "north@plant-north.example")
    b, b_contact = make_partner("Завод Юг", "300000222", "south@plant-south.example")
    staff = CustomUser.objects.create_user(email="catalog-head@staff.example", username="catalog-head", password="x")
    CompanyMember.objects.create(
        user=staff,
        company=seller_company,
        role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Участник", "sort_order": 90})[0],
        is_active=True,
        is_primary=True,
    )
    kw = {"owner": seller_company, "uom": uom, "category": category, "brand": brand}
    cards = {
        "draft": make_card("Болт А-1", "DRAFT", source=a, mpn="A-1", **kw),
        "review": make_card("Болт А-2", "REVIEW", source=a, mpn="A-2", **kw),
        "returned": make_card("Болт А-3", "RETURNED", source=a, mpn="A-3", **kw),
        "published": make_card("Болт А-4", "PUBLISHED", source=a, mpn="A-4", **kw),
        # карточка Б: у А нет ни её, ни цены по ней
        "b_only": make_card("Секретная деталь Б-1", "PUBLISHED", source=b, mpn="B-1", **kw),
        # общая опубликованная карточка: у обоих есть цена; цена Б у А показана быть не должна
        "shared": make_card("Общая деталь", "PUBLISHED", source=b, mpn="S-1", **kw),
        # неопубликованная карточка Б, на которую у А есть цена: статус её хода А не раскрывается
        "b_draft_with_a_offer": make_card(
            "Деталь Б-2 в работе",
            "DRAFT",
            source=b,
            mpn="B-2",
            description="Секретное описание Б-2",
            hs_code="8708301009",
            **kw,
        ),
    }
    today = timezone.localdate()
    offers = {
        "draft": make_offer(cards["draft"], a, "100.00", valid_until=today + timedelta(days=60)),
        "published": make_offer(cards["published"], a, "250.50", valid_until=today + timedelta(days=3)),
        "shared": make_offer(cards["shared"], a, "11.00"),
        "shared_b": make_offer(cards["shared"], b, "9.99", currency="EUR"),
        # у А своё название, бренд и артикул строки: по ним кабинет показывает ему сопоставленную чужую карточку
        "b_draft_a": make_offer(
            cards["b_draft_with_a_offer"],
            a,
            "7.00",
            supplier_item_name="Моя деталь Б-2",
            supplier_brand="Аквилон",
            supplier_mpn="B-2",
        ),
        "b_only": make_offer(cards["b_only"], b, "555.55"),
    }
    ProductReview.objects.create(
        product=cards["returned"],
        submitted_by_contact=a_contact,
        decision=ProductReview.Decision.RETURNED,
        reason="Нет артикула производителя",
        field_issues=[
            {"field": "manufacturer_part_number", "comment": "Укажите артикул по шильдику"},
            {"field": "category", "comment": "Не та категория"},
        ],
        decided_by=staff,
        decided_at=timezone.now(),
    )
    ProductReview.objects.create(product=cards["review"], submitted_by_contact=a_contact)
    return {
        "a": a,
        "a_contact": a_contact,
        "b": b,
        "b_contact": b_contact,
        "own": seller_company,
        "staff": staff,
        "cards": cards,
        "offers": offers,
        "client_a": client_for(a_contact),
        "client_b": client_for(b_contact),
    }


# ── Загрузка прайса: файл, строка, «брокер» без очереди ───────────────────────────────────────────────


def xlsx(records) -> bytes:
    buffer = BytesIO()
    pd.DataFrame(records).to_excel(buffer, index=False)
    return buffer.getvalue()


def row(**extra):
    base = {
        "Наименование": "Вентиль запорный ВЗ-50",
        "Бренд": "Аквилон",
        "Артикул производителя": "AQ-50",
        "Цена": "120.00",
        "Валюта": "USD",
        "Мин. заказ": "10",
        "Срок поставки": "30 дн.",
    }
    base.update(extra)
    return base


@pytest.fixture
def broker(monkeypatch):
    """Выполняет задачу импорта сразу; результат лежит под `task_id` и отдаётся вместо `AsyncResult`."""
    results, calls = {}, []

    def delay(b64, supplier_id, dry_run, **options):
        task_id = uuid.uuid4().hex
        calls.append({"supplier_id": supplier_id, "dry_run": dry_run, **options})
        results[task_id] = run_catalog_import(base64.b64decode(b64), supplier_id, dry_run, **options)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("portal.services.partner_price_list.process_catalog_import.delay", delay)
    monkeypatch.setattr(
        "portal.services.partner_price_list.async_result",
        lambda task_id: SimpleNamespace(
            state="SUCCESS" if task_id in results else "PENDING", result=results.get(task_id)
        ),
    )
    return SimpleNamespace(results=results, calls=calls)


def upload(client, content, **params):
    return client.post(URL, {"file": SimpleUploadedFile("price.xlsx", content), **params}, format="multipart")


def report(client, task_id):
    response = client.get(f"{URL}/{task_id}")
    assert response.status_code == 200, response.content
    return response.json()
