"""Detail-экшены биллинга обязаны проверять объектные права.

Часть экшенов брала `pk` из URL напрямую (`int(pk)`) вместо `self.get_object()`. В DRF
объектные права (`check_object_permissions`) и сужение `get_queryset()` применяются ТОЛЬКО
внутри `get_object()`, поэтому такой экшен обходил обе защиты: доступ зависел исключительно
от того, проверяет ли что-то сам сервис.

Для большинства экшенов сервис проверял (`record_payment` — членство покупателя,
`generate_act` — роутинг продавца, подпись договора — `viewer_can_sign_*`). Но у подписания
акта и отмены договора проверки не было, и посторонний пользователь мог менять чужие
документы по прямому id.

Эти тесты фиксируют границу: пользователь компании, не участвующей в сделке, не должен
получать доступ ни к одному detail-экшену её документов.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    WorkspaceRole,
)
from crm.models import (
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.services.billing import generate_act, generate_invoice_from_contract

#: Посторонний не должен отличать «нет доступа» от «нет объекта» — оба ответа скрывают
#: существование чужого документа.
DENIED = (403, 404)


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code in ("CLIENT", "SUPPLIER"):
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code in ("DRAFT", "CONTRACT_SIGNED"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code in ("DRAFT", "PENDING_CLIENT", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, **capabilities):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        **capabilities,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(lookups):
    """Сделка покупателя с зароутиненным продавцом — и ПОСТОРОННЯЯ компания вне сделки."""
    buyer_co = _company("Покупатель", "SB903", "CLIENT")
    buyer = _member(buyer_co, "buyer@scope.test", can_buy=True)

    seller_co = _company("Продавец", "SS903", "SUPPLIER")
    seller = _member(seller_co, "seller@scope.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )

    # Компания, не имеющая к сделке НИКАКОГО отношения: ни покупатель, ни зароутиненный продавец.
    outsider_co = _company("Посторонние", "SX903", "CLIENT")
    outsider = _member(outsider_co, "outsider@scope.test", can_buy=True)

    deal = Deal.objects.create(title="Сделка", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=seller,
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-SCOPE-903",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {
        "buyer": buyer,
        "seller": seller,
        "outsider": outsider,
        "deal": deal,
        "contract": contract,
    }


def _signed_act(world):
    """Выпущенный акт по выставленному счёту — то, что посторонний не должен трогать."""
    invoice, error = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert error is None, error
    invoice.status = InvoiceStatus.objects.get(code="ISSUED")
    invoice.save(update_fields=["status"])
    act, error = generate_act(invoice.id, actor=world["seller"])
    assert error is None, error
    return invoice, act


@pytest.mark.django_db
class TestOutsiderCannotTouchForeignAct:
    def test_outsider_cannot_sign_a_foreign_act(self, world):
        """РЕГРЕСС. Экшен брал `int(pk)` вместо `self.get_object()`, а `sign_act` проверял
        только оператора-наблюдателя — посторонний получал HTTP 200 и акт становился SIGNED."""
        _invoice, act = _signed_act(world)

        response = _api(world["outsider"]).post(f"/api/v1/crm/acts/{act.id}/sign/")

        assert response.status_code in DENIED, f"посторонний подписал чужой акт: {response.status_code}"
        act.refresh_from_db()
        assert act.status_code == "ISSUED", "статус чужого акта изменён посторонним"

    def test_outsider_cannot_read_a_foreign_act(self, world):
        """Контроль: чтение уже было закрыто сужением queryset — граница та же."""
        _invoice, act = _signed_act(world)
        response = _api(world["outsider"]).get(f"/api/v1/crm/acts/{act.id}/")
        assert response.status_code in DENIED

    def test_buyer_of_the_deal_still_signs(self, world):
        """Починка не должна закрыть доступ участнику сделки."""
        _invoice, act = _signed_act(world)
        response = _api(world["buyer"]).post(f"/api/v1/crm/acts/{act.id}/sign/")
        assert response.status_code == 200, response.content
        act.refresh_from_db()
        assert act.status_code == "SIGNED"


@pytest.mark.django_db
class TestOutsiderCannotTouchForeignContract:
    """Контроль: договор был защищён и до починки — фиксируем, что граница не потерялась.

    Предположение, что `cancel_contract` уязвим (сервис не проверяет членство), тестом НЕ
    подтвердилось: экшен `cancel` закрыт на уровне вьюсета через
    `operator_permissions = {"cancel": "moderation.force_override"}`, то есть отменять договор
    может только оператор платформы с этой возможностью, а не участник сделки.
    """

    def test_outsider_cannot_cancel_a_foreign_contract(self, world):
        contract = world["contract"]
        response = _api(world["outsider"]).post(f"/api/v1/crm/contracts/{contract.id}/cancel/")
        assert response.status_code in DENIED
        contract.refresh_from_db()
        assert contract.status_code != "CANCELLED"

    def test_participant_cannot_cancel_either(self, world):
        """Отмена договора — операторское действие, не участника сделки."""
        contract = world["contract"]
        response = _api(world["buyer"]).post(f"/api/v1/crm/contracts/{contract.id}/cancel/")
        assert response.status_code == 403
        contract.refresh_from_db()
        assert contract.status_code != "CANCELLED"

    def test_outsider_cannot_sign_a_foreign_contract(self, world):
        """Подпись договора проверялась сервисом (`viewer_can_sign_client`) и до починки.
        Сервисный отказ приходит как 400 с кодом — важен ЭФФЕКТ: подписи не появилось."""
        contract = world["contract"]
        response = _api(world["outsider"]).post(f"/api/v1/crm/contracts/{contract.id}/sign-client/")
        assert response.status_code != 200
        contract.refresh_from_db()
        assert contract.client_signed_at is None


@pytest.mark.django_db
class TestOutsiderCannotTouchForeignInvoice:
    """Контроль: эти два экшена проверял САМ сервис и до починки.

    Отказ приходит кодом 400 с бизнес-кодом в `detail`, а не 403/404 — поэтому проверяем
    ЭФФЕКТ (состояние не изменилось), а не конкретный статус. Побочно это значит, что по
    различию ответов посторонний может узнать о существовании чужого документа; менять коды
    здесь не стал — это контракт API, его читает фронтенд.
    """

    def test_outsider_cannot_record_payment(self, world):
        invoice, _act = _signed_act(world)
        response = _api(world["outsider"]).post(
            f"/api/v1/crm/invoices/{invoice.id}/record-payment/",
            {"amount": "10", "paid_at": "2026-07-29"},
            format="json",
        )
        assert response.status_code != 200
        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal("0"), "посторонний записал платёж по чужому счёту"

    def test_outsider_cannot_generate_act(self, world):
        """Аудит H4: продавец вне роутинга не выпускает акт по чужому счёту."""
        from crm.models import Act

        invoice, _act = _signed_act(world)
        before = Act.objects.filter(invoice=invoice).count()
        response = _api(world["outsider"]).post(f"/api/v1/crm/invoices/{invoice.id}/generate-act/")
        assert response.status_code != 200
        assert Act.objects.filter(invoice=invoice).count() == before, "посторонний выпустил акт"


# ── Сырой CRUD в обход сервисов ───────────────────────────────────────────────


@pytest.mark.django_db
class TestRawCrudIsClosed:
    """Записывающие маршруты коллекций закрыты: запись идёт только через сервисные экшены.

    До починки `POST /crm/payments/` создавал платёж мимо `record_payment`: посторонний
    пользователь вписывал в реестр строку по ЧУЖОМУ счёту (проверено — HTTP 201, сумма −999),
    при этом `amount_paid` счёта не пересчитывался, то есть реестр расходился со счётом.
    """

    def test_raw_payment_create_is_closed(self, world):
        """РЕГРЕСС. Ни постороннему, ни участнику — платёж создаётся только сервисом."""
        from crm.models import Payment

        invoice, _act = _signed_act(world)
        payload = {"invoice": invoice.id, "amount": "-999", "paid_at": "2026-07-29", "reference": "RAW-1"}

        for actor in (world["outsider"], world["buyer"]):
            response = _api(actor).post("/api/v1/crm/payments/", payload, format="json")
            assert response.status_code == 405, f"сырое создание платежа доступно: {response.status_code}"

        assert Payment.objects.filter(invoice=invoice).count() == 0
        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal("0")

    def test_service_path_for_payments_still_works(self, world):
        """Закрытие сырого маршрута не должно ломать штатную фиксацию платежа."""
        invoice, _act = _signed_act(world)
        response = _api(world["buyer"]).post(
            f"/api/v1/crm/invoices/{invoice.id}/record-payment/",
            {"amount": "50", "paid_at": "2026-07-29"},
            format="json",
        )
        assert response.status_code in (200, 201), response.content
        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal("50"), "сервисный путь перестал пересчитывать счёт"

    def test_raw_act_write_is_closed(self, world):
        """Акт выпускается сервисом (с проверкой роутинга), а не сырым POST."""
        invoice, act = _signed_act(world)
        create = _api(world["seller"]).post(
            "/api/v1/crm/acts/",
            {"deal": world["deal"].id, "invoice": invoice.id, "total_amount": "1"},
            format="json",
        )
        assert create.status_code == 405
        patch = _api(world["seller"]).patch(f"/api/v1/crm/acts/{act.id}/", {"total_amount": "1"}, format="json")
        assert patch.status_code == 405
        delete = _api(world["seller"]).delete(f"/api/v1/crm/acts/{act.id}/")
        assert delete.status_code == 405

    def test_act_service_actions_still_work(self, world):
        """Чтение и сервисные экшены акта не должны пострадать от закрытия CRUD."""
        _invoice, act = _signed_act(world)
        assert _api(world["buyer"]).get(f"/api/v1/crm/acts/{act.id}/").status_code == 200
        assert _api(world["buyer"]).post(f"/api/v1/crm/acts/{act.id}/sign/").status_code == 200

    def test_raw_invoice_create_and_delete_are_closed(self, world):
        """Счёт выставляется через create-manual / generate-from-contract, отменяется через
        cancel. Сырое удаление обходило отмену и падало бы в ProtectedError при платежах."""
        invoice, _act = _signed_act(world)
        create = _api(world["seller"]).post("/api/v1/crm/invoices/", {"deal": world["deal"].id}, format="json")
        assert create.status_code == 405
        delete = _api(world["seller"]).delete(f"/api/v1/crm/invoices/{invoice.id}/")
        assert delete.status_code == 405

    def test_raw_fulfillment_write_is_closed(self, world):
        """Сырой CRUD позволял проставить/сбросить `contract` — привязку к владельцу,
        от которой зависит видимость отгрузки для продавца."""
        create = _api(world["seller"]).post("/api/v1/crm/fulfillments/", {"deal": world["deal"].id}, format="json")
        assert create.status_code == 405


# ── Фильтры списков ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestBillingListFilters:
    """Параметры фильтрации молча отбрасывались: у вьюсетов не было ни `filterset_fields`,
    ни `filterset_class`, а `DjangoFilterBackend` в таком случае возвращает queryset без
    изменений — без ошибки. Симптомы были видны пользователю (см. тесты ниже)."""

    def _second_deal_invoice(self, world):
        """Второй счёт по ДРУГОЙ сделке того же покупателя — чтобы фильтр было что отсечь."""
        from crm.models import Contract, ContractStatus, Deal, DealSellerRouting, Quote, QuoteStatus

        other_deal = Deal.objects.create(
            title="Вторая сделка",
            company=world["deal"].company,
            stage=DealStage.objects.get(code="CONTRACT_SIGNED"),
        )
        DealSellerRouting.objects.create(deal=other_deal, seller_company=world["seller"].memberships.first().company)
        other_quote = Quote.objects.create(
            deal=other_deal,
            version=1,
            status=QuoteStatus.objects.get(code="DRAFT"),
            prepared_by=world["seller"],
            seller_company=world["seller"].memberships.first().company,
            total_incl_vat=Decimal("50"),
        )
        other_contract = Contract.objects.create(
            deal=other_deal,
            quote=other_quote,
            number="CT-SCOPE-OTHER",
            status=ContractStatus.objects.get(code="SIGNED"),
            total_amount=Decimal("50"),
        )
        invoice, error = generate_invoice_from_contract(other_contract.id, actor=None)
        assert error is None, error
        return other_deal, invoice

    def _rows(self, response):
        body = response.json()
        return body["results"] if isinstance(body, dict) and "results" in body else body

    def test_deal_filter_actually_filters(self, world):
        """РЕГРЕСС. `?deal=<id>` отбрасывался, и список возвращал ВСЕ видимые счета."""
        first_invoice, _act = _signed_act(world)
        _other_deal, other_invoice = self._second_deal_invoice(world)

        response = _api(world["buyer"]).get(f"/api/v1/crm/invoices/?deal={world['deal'].id}")

        assert response.status_code == 200, response.content
        ids = {row["id"] for row in self._rows(response)}
        assert first_invoice.id in ids
        assert other_invoice.id not in ids, "фильтр по сделке не сработал"

    def test_status_filter_accepts_a_comma_separated_list(self, world):
        """РЕГРЕСС. `RecordPaymentDialog` шлёт `?status=ISSUED,PARTIAL,OVERDUE`, чтобы
        предложить к оплате только живую дебиторку. Фильтр игнорировался — в списке
        оказывались черновики и отменённые счета, и пользователь выбирал неоплачиваемый."""
        issued_invoice, _act = _signed_act(world)  # ISSUED
        _other_deal, draft_invoice = self._second_deal_invoice(world)  # DRAFT
        assert draft_invoice.status_code == "DRAFT"

        response = _api(world["seller"]).get("/api/v1/crm/invoices/?status=ISSUED,PARTIAL,OVERDUE")

        assert response.status_code == 200, response.content
        ids = {row["id"] for row in self._rows(response)}
        assert issued_invoice.id in ids
        assert draft_invoice.id not in ids, "черновик попал в список к оплате"

    def test_unknown_status_returns_nothing_rather_than_everything(self, world):
        """Осмысленный отказ: неизвестный код не должен вести себя как «фильтра нет»."""
        _signed_act(world)
        response = _api(world["buyer"]).get("/api/v1/crm/invoices/?status=НЕТ_ТАКОГО")
        assert response.status_code == 200
        assert self._rows(response) == []

    def test_payments_can_be_filtered_by_deal(self, world):
        """У платежа нет своей связи со сделкой — фильтр идёт через счёт."""
        invoice, _act = _signed_act(world)
        _api(world["buyer"]).post(
            f"/api/v1/crm/invoices/{invoice.id}/record-payment/",
            {"amount": "10", "paid_at": "2026-07-29"},
            format="json",
        )
        response = _api(world["buyer"]).get(f"/api/v1/crm/payments/?deal={world['deal'].id}")
        assert response.status_code == 200, response.content
        assert len(self._rows(response)) == 1

    def test_acts_can_be_filtered_by_deal(self, world):
        _invoice, act = _signed_act(world)
        response = _api(world["buyer"]).get(f"/api/v1/crm/acts/?deal={world['deal'].id}")
        assert response.status_code == 200, response.content
        assert {row["id"] for row in self._rows(response)} == {act.id}
