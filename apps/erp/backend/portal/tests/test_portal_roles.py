"""PART-1 (ADR-0022): вход партнёра в кабинет, роли сессии, модули `/me`, эндпоинты по модулям.

Доступ = тип CLIENT или отношение `partner` (приглашён/активен); приостановленное отношение закрывает вход и гасит
живую сессию. Роли складываются (клиент и партнёр), модули — клиентские плюс включённые партнёру на отношении. Эндпоинт
портала открыт сессии с его модулем, иначе 403 `MODULE_REQUIRED` — один общий класс `HasPortalModule`, а тесты ниже
перебирают ВСЕ операции контракта, а не выбранные руками.
"""

import re

import pytest
from django.conf import settings as dj_settings
from django.core import mail
from parties.models import Company, CompanyRelationship, CompanyType, Contact, RelationshipRole, RelationshipStatus
from portal.models import MagicLinkToken
from portal.services.access import (
    activate_on_first_login,
    cabinet_company_q,
    company_access,
    company_has_cabinet_access,
    company_roles,
)
from portal.services.invitation import invite_contact
from portal.services.roles import CLIENT_MODULES, ROLE_DEFAULT_MODULES, ROLE_MODULES
from portal.tests.conftest import LOCMEM_BACKEND, PortalAPIClient, make_portal_session
from portal.tests.contract_support import OpenApiContract, component
from rest_framework import status

PREFIX = "/api/portal/v1"
ME = f"{PREFIX}/me"
CODE_URL = f"{PREFIX}/auth/code"
MAGIC_LINK_URL = f"{PREFIX}/auth/magic-link"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem_mail(settings, inline_magic_link_task):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"
    mail.outbox.clear()


@pytest.fixture
def supplier_company(db):
    """Поставщик: тип SUPPLIER без CLIENT (сигнал «SUPPLIER ⇒ CLIENT» снят в K0)."""
    company = Company.objects.create(name="OOO Supplier North", inn="300000555")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    assert not company.types.filter(code="CLIENT").exists()
    return company


@pytest.fixture
def supplier_contact(supplier_company):
    return Contact.objects.create(
        company=supplier_company,
        name="Dilshod Supplier",
        email="dilshod@supplier-north.example.uz",
        language="uz",
        can_act=True,  # как у контакта, заведённого в блоке «Доступ в кабинет»
    )


def relate(company, status_=RelationshipStatus.ACTIVE, **extra):
    extra.setdefault("modules", list(ROLE_DEFAULT_MODULES["partner"]))
    return CompanyRelationship.objects.create(company=company, role=RelationshipRole.PARTNER, status=status_, **extra)


def client_for(session) -> PortalAPIClient:
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


@pytest.fixture
def partner_client(supplier_company, supplier_contact):
    relate(supplier_company)
    return client_for(make_portal_session(supplier_contact, supplier_company, "magic_link"))


class TestAccessRule:
    def test_supplier_without_relationship_is_closed(self, supplier_company):
        assert company_has_cabinet_access(supplier_company.pk) is False
        assert company_roles(supplier_company.pk) == []

    @pytest.mark.parametrize(
        ("status_", "open_"),
        [
            (RelationshipStatus.INVITED, True),
            (RelationshipStatus.ACTIVE, True),
            (RelationshipStatus.SUSPENDED, False),
        ],
    )
    def test_relationship_status_decides(self, supplier_company, status_, open_):
        relate(supplier_company, status_)
        assert company_has_cabinet_access(supplier_company.pk) is open_
        assert company_roles(supplier_company.pk) == (["partner"] if open_ else [])
        assert Company.objects.filter(cabinet_company_q(), pk=supplier_company.pk).exists() is open_

    def test_client_keeps_access_by_type_without_relationship(self, client_company):
        assert company_has_cabinet_access(client_company.pk) is True
        assert company_roles(client_company.pk) == ["client"]

    def test_company_can_be_client_and_partner(self, client_company):
        relate(client_company)
        assert company_roles(client_company.pk) == ["client", "partner"]
        roles, modules = company_access(client_company.pk)
        assert roles == ["client", "partner"] and modules == [*CLIENT_MODULES, "my_products"]

    def test_archived_supplier_is_closed_even_with_active_relationship(self, supplier_company):
        relate(supplier_company)
        supplier_company.is_active = False
        supplier_company.save(update_fields=["is_active"])
        assert company_has_cabinet_access(supplier_company.pk) is False

    def test_own_company_never_enters_by_relationship(self, seller_company, settings):
        settings.OWN_COMPANY_ID = seller_company.pk
        relate(seller_company)
        assert company_has_cabinet_access(seller_company.pk) is False

    def test_relationship_of_another_company_does_not_open_this_one(self, supplier_company):
        other = Company.objects.create(name="OOO Other Supplier", inn="300000556")
        relate(other)
        assert company_has_cabinet_access(supplier_company.pk) is False

    def test_relationship_is_unique_per_company_and_role(self, supplier_company):
        from django.db import IntegrityError, transaction

        relate(supplier_company)
        with pytest.raises(IntegrityError), transaction.atomic():
            relate(supplier_company, RelationshipStatus.INVITED)


class TestEntryPaths:
    """Все пути входа решает одна функция: приглашение, ссылка/код, Telegram."""

    def _request_code(self, contact, client=None):
        """Приглашение письмом → код из `mail.outbox`."""
        outcome = invite_contact(contact, channel="email")
        assert outcome.error is None, outcome.error
        body = mail.outbox[-1].body
        return re.search(r"\b(\d{6})\b", body).group(1)

    def test_invitation_to_closed_supplier_is_refused(self, supplier_contact):
        outcome = invite_contact(supplier_contact, channel="email")
        assert outcome.error == "COMPANY_NOT_CLIENT"
        assert mail.outbox == []

    def test_invited_supplier_logs_in_by_code_and_relationship_becomes_active(
        self, supplier_company, supplier_contact, anon_portal_client
    ):
        relationship = relate(supplier_company, RelationshipStatus.INVITED)
        code = self._request_code(supplier_contact)

        response = anon_portal_client.post(CODE_URL, {"email": supplier_contact.email, "code": code}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        relationship.refresh_from_db()
        assert relationship.status == RelationshipStatus.ACTIVE and relationship.activated_at is not None
        me = anon_portal_client.get(ME)
        assert me.status_code == 200
        assert me.json()["roles"] == ["partner"] and me.json()["modules"] == [
            "my_products",
            "catalog_requests",
            "messages",
            "profile",
        ]

    def test_invitation_mail_for_supplier_has_no_client_sections(self, supplier_company, supplier_contact):
        relate(supplier_company, RelationshipStatus.INVITED)
        self._request_code(supplier_contact)
        body = mail.outbox[-1].body  # язык контакта — uz
        assert "mahsulotlaringiz va narxlaringiz" in body
        assert "tijorat takliflaringiz" not in body

    def test_magic_link_request_for_suspended_supplier_sends_nothing(
        self, supplier_company, supplier_contact, anon_portal_client
    ):
        relate(supplier_company, RelationshipStatus.SUSPENDED)
        response = anon_portal_client.post(MAGIC_LINK_URL, {"email": supplier_contact.email}, format="json")
        assert response.status_code == 200 and mail.outbox == []

    def test_magic_link_request_for_active_supplier_sends_mail(
        self, supplier_company, supplier_contact, anon_portal_client
    ):
        relate(supplier_company)
        response = anon_portal_client.post(MAGIC_LINK_URL, {"email": supplier_contact.email}, format="json")
        assert response.status_code == 200 and len(mail.outbox) == 1

    def test_code_issued_before_suspension_does_not_log_in(
        self, supplier_company, supplier_contact, anon_portal_client
    ):
        relationship = relate(supplier_company, RelationshipStatus.INVITED)
        code = self._request_code(supplier_contact)
        relationship.status = RelationshipStatus.SUSPENDED
        relationship.save()

        response = anon_portal_client.post(CODE_URL, {"email": supplier_contact.email, "code": code}, format="json")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json() == {"detail": "LOGIN_CODE_INVALID"}
        assert not MagicLinkToken.objects.filter(contact=supplier_contact, used_at__isnull=False).exists()

    def test_suspension_kills_live_session_on_next_request(self, partner_client, supplier_company):
        assert partner_client.get(ME).status_code == 200
        CompanyRelationship.objects.filter(company=supplier_company).update(status=RelationshipStatus.SUSPENDED)
        response = partner_client.get(ME)
        assert response.status_code == 401 and response.json() == {"detail": "UNAUTHORIZED"}

    def test_resumed_relationship_restores_session(self, partner_client, supplier_company):
        CompanyRelationship.objects.filter(company=supplier_company).update(status=RelationshipStatus.SUSPENDED)
        assert partner_client.get(ME).status_code == 401
        CompanyRelationship.objects.filter(company=supplier_company).update(status=RelationshipStatus.ACTIVE)
        assert partner_client.get(ME).status_code == 200

    def test_activation_does_not_resurrect_suspended(self, supplier_company):
        relationship = relate(supplier_company, RelationshipStatus.SUSPENDED)
        activate_on_first_login(supplier_company.pk)
        relationship.refresh_from_db()
        assert relationship.status == RelationshipStatus.SUSPENDED


class TestMe:
    def test_client_me_has_client_role_and_the_whole_current_menu(self, portal_client):
        body = portal_client.get(ME).json()
        assert body["roles"] == ["client"]
        assert body["modules"] == list(CLIENT_MODULES)

    def test_partner_me_defaults(self, partner_client):
        body = partner_client.get(ME).json()
        assert body["roles"] == ["partner"] and body["modules"] == [
            "my_products",
            "catalog_requests",
            "messages",
            "profile",
        ]

    def test_partner_me_follows_enabled_modules_at_once(self, partner_client, supplier_company):
        CompanyRelationship.objects.filter(company=supplier_company).update(modules=["my_products"])
        assert partner_client.get(ME).json()["modules"] == ["my_products", "messages", "profile"]
        CompanyRelationship.objects.filter(company=supplier_company).update(modules=[])
        body = partner_client.get(ME).json()
        # доступ открыт, разделы не настроены: остаются «Сообщения» и «Профиль» — они есть у любой сессии (CHAT-1)
        assert body["roles"] == ["partner"] and body["modules"] == ["messages", "profile"]

    def test_client_and_partner_roles_and_modules_add_up(self, client_company, portal_client):
        relate(client_company, modules=["my_products"])
        body = portal_client.get(ME).json()
        assert body["roles"] == ["client", "partner"]
        assert body["modules"] == [*CLIENT_MODULES, "my_products"]
        assert portal_client.get(PREFIX + "/quotes").status_code == 200  # клиентские эндпоинты открыты

    def test_modules_outside_the_role_template_open_nothing(self, partner_client, supplier_company):
        """Мусор в базе (чужой модуль, повтор) не открывает ни меню, ни эндпоинтов."""
        CompanyRelationship.objects.filter(company=supplier_company).update(
            modules=["quotes", "invoices", "my_products", "my_products"]
        )
        assert partner_client.get(ME).json()["modules"] == ["my_products", "messages", "profile"]
        assert partner_client.get(PREFIX + "/quotes").status_code == 403
        assert partner_client.get(PREFIX + "/invoices").status_code == 403

    def test_templates_match_the_contract(self):
        """Шаблон «роль → модули» — данные ERP, контракт несёт тот же (`Me.x-role-modules`, перечень `ModuleCode`)."""
        contract = OpenApiContract("erp-portal.yaml").load()
        schemas = contract["components"]["schemas"]
        assert {role: list(modules) for role, modules in ROLE_MODULES.items()} == schemas["Me"]["x-role-modules"]
        assert {role: list(modules) for role, modules in ROLE_DEFAULT_MODULES.items()} == schemas["Me"][
            "x-role-default-modules"
        ]
        assert set(schemas["ModuleCode"]["enum"]) == {m for modules in ROLE_MODULES.values() for m in modules}
        assert set(schemas["PortalRole"]["enum"]) == {role.value for role in RelationshipRole}
        assert "MODULE_REQUIRED" in component("ErrorCode")["x-extensible-enum"]


# ── Эндпоинты по модулям ───────────────────────────────────────────────────────────────────────────

#: Операции, открытые любой роли или без сессии: вход, выход и профиль, а также чат кабинета — модуль `messages` есть у
#: любой сессии и не выключается (CHAT-1, `ALWAYS_ON`). Всё остальное в контракте — по модулям.
ANY_ROLE_PATHS = {
    "/auth/telegram",
    "/auth/magic-link",
    "/auth/magic",
    "/auth/code",
    "/auth/logout",
    "/me",
    "/messages",
    "/messages/read",
}
#: NOTIFY-1: Telegram — личная настройка контакта (модуль `profile` есть у любой сессии).
ANY_ROLE_PATHS |= {"/me/telegram", "/me/telegram/test", "/me/telegram-link"}
#: Колокольчик (NOTIFY-2) — модуль `profile`, он есть у любой сессии: лента фильтруется по модулям, а не закрывается
ANY_ROLE_PATHS |= {"/notifications", "/notifications/read", "/notifications/settings"}
#: Публичная проверка подлинности документов (ADR-0024 §6, SIGN-VERIFY-1): доступна без сессии и модулей.
ANY_ROLE_PATHS |= {"/verify/{code}"}
#: Управление сессиями контакта (J2): личная безопасность контакта, доступна любой роли.
ANY_ROLE_PATHS |= {"/auth/sessions", "/auth/sessions/revoke-others"}
#: Публичная подача заявки «Стать партнёром» (ADR-0022, DECISIONS 2026-11-05, PART-ONBOARD).
ANY_ROLE_PATHS |= {"/auth/partner-application"}
#: Справочник стран для онбординга и профиля (COUNTRY-MASK-1): доступен публично.
ANY_ROLE_PATHS |= {"/countries"}

#: Эндпоинты модуля «Каталог и заявки» (`catalog_requests`): заявки, каталог и загрузка вложений.
CATALOG_REQUESTS_PATHS = {
    "/requests",
    "/requests/{id}",
    "/requests/{id}/reorder",
    "/catalog",
    "/catalog/{id}",
    "/catalog/{id}/documents/{doc_id}/file",
    "/catalog/categories",
    "/uploads",
}

#: Эндпоинты модуля «Мои товары» (`my_products`, PART-2): раздел партнёра; клиентскому набору модулей они не открыты.
MY_PRODUCTS_PATHS = {
    "/partner/products",
    "/partner/products/{id}",
    "/partner/products/submit",
    "/partner/offers/confirm",
    "/partner/price-template",
    "/partner/price-list",
    "/partner/price-list/{task_id}",
    "/partner/orders",
    "/partner/orders/{id}",
    "/partner/orders/{id}/confirm",
    "/partner/orders/{id}/ship",
    "/partner/price-requests",
    "/partner/price-requests/{id}",
    "/partner/price-requests/{id}/respond",
}


def _client_operations(only=None, exclude=None):
    operations = OpenApiContract("erp-portal.yaml").operations()
    return sorted(
        (method, path)
        for method, path in operations
        if path not in ANY_ROLE_PATHS and (only is None or path in only) and (exclude is None or path not in exclude)
    )


def _concrete(path: str) -> str:
    return PREFIX + re.sub(r"\{[^}]+\}", "1", path)


def _only_my_products(supplier_company):
    CompanyRelationship.objects.filter(company=supplier_company).update(modules=["my_products"])


class TestEndpointsFollowModules:
    def test_every_operation_of_the_contract_is_covered(self):
        operations = _client_operations()
        assert len(operations) >= 25  # сторож от пустого перебора, если контракт переименуют
        paths = {path for _method, path in operations}
        for expected in ("/requests", "/quotes", "/contracts", "/invoices", "/acts", "/deliveries", "/documents"):
            assert expected in paths
        for expected in ("/uploads", "/catalog", "/catalog/categories", "/company", "/team", "/team/invite"):
            assert expected in paths
        assert CATALOG_REQUESTS_PATHS <= paths
        assert MY_PRODUCTS_PATHS <= paths

    @pytest.mark.parametrize(("method", "path"), _client_operations(exclude=MY_PRODUCTS_PATHS))
    def test_partner_without_modules_gets_403_on_every_operation(self, partner_client, supplier_company, method, path):
        _only_my_products(supplier_company)
        response = getattr(partner_client, method.lower())(_concrete(path), {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN, (method, path, response.content)
        assert response.json() == {"detail": "MODULE_REQUIRED"}

    @pytest.mark.parametrize(("method", "path"), _client_operations(exclude=MY_PRODUCTS_PATHS))
    def test_403_does_not_depend_on_the_object_existing(self, partner_client, supplier_company, method, path):
        """Модуль проверяется до поиска объекта: ответ не зависит от того, есть ли объект."""
        _only_my_products(supplier_company)
        response = getattr(partner_client, method.lower())(_concrete(path).replace("/1", "/999999"), {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize(("method", "path"), _client_operations(exclude=CATALOG_REQUESTS_PATHS | MY_PRODUCTS_PATHS))
    def test_default_partner_never_reaches_client_documents(self, partner_client, method, path):
        """Партнёр с модулями по умолчанию: КП, договоры, счета, акты, поставки, документы, команда — только клиенту."""
        response = getattr(partner_client, method.lower())(_concrete(path), {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN, (method, path)
        assert response.json() == {"detail": "MODULE_REQUIRED"}

    @pytest.mark.parametrize(("method", "path"), _client_operations(only=MY_PRODUCTS_PATHS))
    def test_my_products_endpoints_need_exactly_that_module(self, partner_client, supplier_company, method, path):
        """Партнёр с одним `catalog_requests` в «Мои товары» не попадает: 403 до поиска объекта; клиентские модули не открывают их."""
        CompanyRelationship.objects.filter(company=supplier_company).update(modules=["catalog_requests"])
        response = getattr(partner_client, method.lower())(_concrete(path), {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN and response.json() == {"detail": "MODULE_REQUIRED"}

    @pytest.mark.parametrize(("method", "path"), _client_operations(only=MY_PRODUCTS_PATHS))
    def test_client_company_never_reaches_my_products(self, portal_client, method, path):
        response = getattr(portal_client, method.lower())(_concrete(path), {}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN and response.json() == {"detail": "MODULE_REQUIRED"}

    def test_default_partner_reads_catalog_and_requests(self, partner_client):
        for url in ("/catalog", "/catalog/categories", "/requests"):
            assert partner_client.get(PREFIX + url).status_code == 200, url

    def test_catalog_for_partner_is_the_published_layer_without_suppliers(self, partner_client, supplier_company):
        """Каталог партнёра — тот же опубликованный слой, что у клиента: поставщиков и закупочных цен в нём нет."""
        response = partner_client.get(PREFIX + "/catalog")
        assert response.status_code == 200
        text = response.content.decode().lower()
        for forbidden in ("supplier", "base_price", "margin", supplier_company.name.lower()):
            assert forbidden not in text

    def test_catalog_document_file_follows_the_catalog_requests_module(self, partner_client, supplier_company):
        """CAT-CARD-2: файл документа карточки — тот же модуль, что каталог: партнёр с модулем скачивает, без него — 403."""
        from django.core.files.base import ContentFile

        from catalog.models import Product, ProductStatus, TechDocument

        product = Product.objects.create(
            name="Карточка для партнёра", status=ProductStatus.objects.get_or_create(code="PUBLISHED")[0]
        )
        document = TechDocument(kind="passport", title="Паспорт", client_visible=True, product=product)
        document.file.save("p.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
        url = f"{PREFIX}/catalog/{product.pk}/documents/{document.pk}/file"
        assert partner_client.get(url).status_code == 200
        _only_my_products(supplier_company)
        denied = partner_client.get(url)
        assert denied.status_code == 403 and denied.json() == {"detail": "MODULE_REQUIRED"}

    def test_toggle_takes_effect_without_relogin(self, partner_client, supplier_company):
        assert partner_client.get(PREFIX + "/catalog").status_code == 200
        _only_my_products(supplier_company)
        off = partner_client.get(PREFIX + "/catalog")
        assert off.status_code == 403 and off.json() == {"detail": "MODULE_REQUIRED"}
        assert partner_client.get(PREFIX + "/requests").status_code == 403
        CompanyRelationship.objects.filter(company=supplier_company).update(modules=["my_products", "catalog_requests"])
        assert partner_client.get(PREFIX + "/catalog").status_code == 200

    def test_uploads_follow_the_catalog_requests_module(self, partner_client, supplier_company):
        assert partner_client.post(PREFIX + "/uploads", {}, format="json").status_code != 403
        _only_my_products(supplier_company)
        assert partner_client.post(PREFIX + "/uploads", {}, format="json").status_code == 403

    def test_verify_document_is_public_and_not_blocked_by_modules(self, partner_client, supplier_company):
        """SIGN-VERIFY-1 (ADR-0024 §6): проверка подлинности доступна публично и не блокируется модулями партнёра."""
        _only_my_products(supplier_company)
        response = partner_client.get(PREFIX + "/verify/NONEXISTENT-CODE")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "NOT_FOUND"}

    def test_can_act_is_the_same_for_partner_and_client(self, partner_client, supplier_contact, readonly_portal_client):
        """Право действовать одинаково у клиента и партнёра: без него — 403 FORBIDDEN на заявке и загрузке, с ним — 201."""
        body = {"summary": "Нужен кабель", "lines": [{"text": "Кабель"}]}
        supplier_contact.can_act = False
        supplier_contact.save(update_fields=["can_act"])
        for url, payload in (("/requests", body), ("/uploads", {})):
            denied = partner_client.post(PREFIX + url, payload, format="json")
            assert denied.status_code == 403 and denied.json() == {"detail": "FORBIDDEN"}, url
        assert readonly_portal_client.post(PREFIX + "/requests", body, format="json").status_code == 403

        supplier_contact.can_act = True
        supplier_contact.save(update_fields=["can_act"])
        assert partner_client.post(PREFIX + "/requests", body, format="json").status_code == 201
        assert partner_client.post(PREFIX + "/uploads", {}, format="json").status_code != 403

    def test_partner_request_without_crm_mapping_is_not_lost(self, partner_client, supplier_company, django_user_model):
        """Компания не сопоставлена клиенту CRM, `request.created` не уходит: ответственный сотрудник получает уведомление."""
        from notifications.models import Notification

        staff = django_user_model.objects.create_user(email="supply-resp@d2-3.test", username="resp", password="x")
        CompanyRelationship.objects.filter(company=supplier_company).update(responsible=staff)
        body = {"summary": "Нужен кабель", "lines": [{"text": "Кабель"}]}

        assert partner_client.post(PREFIX + "/requests", body, format="json").status_code == 201

        note = Notification.objects.get(user=staff, event_code="portal.partner_request_unrouted")
        assert supplier_company.name in note.title and note.deal_id is not None

    def test_unrouted_partner_request_goes_to_platform_admins_without_responsible(
        self, partner_client, supplier_company
    ):
        from notifications.models import Notification

        CompanyRelationship.objects.filter(company=supplier_company).update(responsible=None)
        body = {"summary": "Нужен кабель", "lines": [{"text": "Кабель"}]}
        assert partner_client.post(PREFIX + "/requests", body, format="json").status_code == 201
        assert Notification.objects.filter(
            audience=Notification.AUDIENCE_PLATFORM_ADMIN, event_code="portal.partner_request_unrouted"
        ).exists()

    def test_client_request_does_not_notify_about_routing(self, portal_client):
        from notifications.models import Notification

        body = {"summary": "Нужен кабель", "lines": [{"text": "Кабель"}]}
        assert portal_client.post(PREFIX + "/requests", body, format="json").status_code == 201
        assert not Notification.objects.filter(event_code="portal.partner_request_unrouted").exists()

    def test_profile_module_is_always_there_and_never_switched_off(self, partner_client, supplier_company):
        for modules in (["my_products", "catalog_requests"], ["my_products"], []):
            CompanyRelationship.objects.filter(company=supplier_company).update(modules=modules)
            assert "profile" in partner_client.get(ME).json()["modules"]
        assert partner_client.post(PREFIX + "/auth/logout").status_code in (200, 204)

    def test_client_is_not_affected(self, portal_client):
        for url in ("/requests", "/quotes", "/catalog", "/company", "/team"):
            assert portal_client.get(PREFIX + url).status_code == 200, url

    def test_unauthenticated_is_still_401_not_403(self, anon_portal_client):
        assert anon_portal_client.get(PREFIX + "/requests").status_code == 401

    def test_view_without_declared_module_is_closed(self, portal_client, monkeypatch):
        """Fail-closed: новая вьюха, не назвавшая модуль, не открыта никому, даже клиенту."""
        from portal.views import QuoteListView

        monkeypatch.delattr(QuoteListView, "required_module")
        assert portal_client.get(PREFIX + "/quotes").status_code == 403

    def test_every_portal_view_declares_its_module(self):
        """Структурная страховка: любая вьюха портала с сессией проходит через `HasPortalModule` и называет модуль."""
        from django.urls import get_resolver
        from portal.authentication import PortalAuthentication
        from portal.permissions import HasPortalModule
        from portal.views import BasePortalView

        seen = 0
        for pattern in get_resolver().url_patterns:
            if "portal" not in str(pattern.pattern):
                continue
            for sub in getattr(pattern, "url_patterns", []):
                view_class = getattr(getattr(sub, "callback", None), "cls", None)
                if view_class is None or PortalAuthentication not in view_class.authentication_classes:
                    continue
                if not issubclass(view_class, BasePortalView):
                    continue  # выход (`/auth/logout`) — любая сессия, у него нет прав вовсе
                seen += 1
                assert HasPortalModule in view_class.permission_classes, view_class
                assert getattr(view_class, "required_module", None), view_class
        assert seen >= 25
