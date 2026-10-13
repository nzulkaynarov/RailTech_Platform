"""Закрывающий документ по счёту ОДИН, а возвращённый акт выпускается заново.

Находка прогона 20-08, подтверждённая замером 24-08: три нажатия «Сформировать акт» по счёту
на 112 давали ТРИ акта с разными номерами на 336 суммарно. Защиты не было ни в модели (FK без
`unique`), ни в сервисе (ни одного обращения к `invoice.acts` перед `Act.objects.create`), ни
на кнопке.

Вторая половина того же дефекта: отклонение возвращает акт в DRAFT, а диалог отказа обещает
заказчику «исполнитель увидит причину и выставит акт заново» — но пути для этого не
существовало. У DRAFT-акта оставалась одна кнопка «Аннулировать», и «выставить заново»
получалось только со страницы счетов, то есть ВТОРЫМ документом.

Эталон — Odoo: исправленный черновик подтверждают, а не создают рядом второй; исправление
выпущенного документа оформляется отдельной сущностью (кредит-нота), которой у нас нет.
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
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import (
    Act,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    verified = VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})[
        0
    ]

    def company(name, inn, type_code):
        obj = Company.objects.create(name=name, inn=inn, verification_status=verified)
        obj.types.add(CompanyType.objects.get(code=type_code))
        return obj

    def member(comp, email, **caps):
        user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
        CompanyMember.objects.create(
            user=user,
            company=comp,
            role=WorkspaceRole.objects.get(code="OWNER"),
            is_active=True,
            is_primary=True,
            **caps,
        )
        return user

    buyer_co = company("Buyer ONE", "B900", "CLIENT")
    buyer_user = member(buyer_co, "buyer@one-act.test", can_buy=True, can_sell=False)
    seller_co = company("Seller ONE", "S900", "SUPPLIER")
    seller_user = member(seller_co, "seller@one-act.test", can_sell=True, can_buy=False)
    SupplierSubscription.objects.create(
        company=seller_co, plan="PREMIUM", status="ACTIVE", valid_until=timezone.localdate() + timedelta(days=30)
    )

    deal = Deal.objects.create(title="One act deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-ONE-001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
        # Подсказка цепочки начинается с договора: без ОБЕИХ подписей она законно требует
        # подписать его, и до участка акта дело не доходит.
        client_signed_at=timezone.now(),
        manager_signed_at=timezone.now(),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-ONE-001",
        status=InvoiceStatus.objects.get(code="PAID"),
        total_incl_vat=Decimal("112"),
        amount_paid=Decimal("112"),
    )
    # Поставка состоялась: закрывающий документ появляется по ФАКТУ ПОСТАВКИ (G1), и без
    # принятой отгрузки участок акта в подсказке не наступает.
    from crm.models import Fulfillment, FulfillmentStatus

    Fulfillment.objects.create(deal=deal, status=FulfillmentStatus.objects.get(code="ACCEPTED"))
    return {
        "deal": deal,
        "invoice": invoice,
        "buyer_user": buyer_user,
        "seller_user": seller_user,
    }


def _generate(world):
    return _api(world["seller_user"]).post(f"/api/v1/crm/invoices/{world['invoice'].id}/generate-act/")


# ── Один живой акт на счёт ──────────────────────────────────────────────────


def test_second_click_does_not_produce_a_second_act(world):
    first = _generate(world)
    assert first.status_code == 201, first.content

    second = _generate(world)

    assert second.status_code == 400
    assert second.json()["detail"].split(":")[0] == "ACT_ALREADY_EXISTS"
    assert Act.objects.filter(invoice=world["invoice"]).count() == 1, "второго закрывающего документа быть не может"


def test_refusal_names_the_existing_act(world):
    """Отказ обязан ПОКАЗАТЬ, где документ, а не просто отбить: иначе продавец решит, что
    выпуск не сработал, и будет жать снова."""
    _generate(world)
    existing = Act.objects.get(invoice=world["invoice"])

    resp = _generate(world)

    assert resp.json()["detail"] == f"ACT_ALREADY_EXISTS:{existing.id}"


def test_a_cancelled_act_frees_the_invoice(world):
    """Аннулированный акт — отменённый документ, а не выпущенный: по счёту можно выпустить
    новый. Иначе аннулирование становилось бы тупиком."""
    _generate(world)
    act = Act.objects.get(invoice=world["invoice"])
    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/cancel/", {"reason": "ошибка в позициях"})
    assert resp.status_code == 200, resp.content

    again = _generate(world)

    assert again.status_code == 201, again.content
    assert Act.objects.filter(invoice=world["invoice"]).count() == 2
    assert Act.objects.filter(invoice=world["invoice"], status__code="ISSUED").count() == 1


# ── Возвращённый акт выпускается заново ─────────────────────────────────────


def _rejected_act(world):
    _generate(world)
    act = Act.objects.get(invoice=world["invoice"])
    resp = _api(world["buyer_user"]).post(f"/api/v1/crm/acts/{act.id}/reject/", {"reason": "объём не совпал"})
    assert resp.status_code == 200, resp.content
    act.refresh_from_db()
    assert act.status_code == "DRAFT"
    return act


def test_rejected_act_is_reissued_not_duplicated(world):
    act = _rejected_act(world)

    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/reissue/")

    assert resp.status_code == 200, resp.content
    act.refresh_from_db()
    assert act.status_code == "ISSUED"
    assert act.rejection_reason == "", "на выпущенном заново акте не висит прошлый отказ"
    assert act.issuer_signed_at is not None
    assert Act.objects.filter(invoice=world["invoice"]).count() == 1, "документ ТОТ ЖЕ, номер сохраняется"


def test_generate_act_points_at_the_returned_one_instead_of_duplicating(world):
    """Кнопка на счёте больше не порождает второй документ, а называет возвращённый."""
    act = _rejected_act(world)

    resp = _generate(world)

    assert resp.status_code == 400
    assert resp.json()["detail"] == f"ACT_AWAITING_REISSUE:{act.id}"
    assert Act.objects.filter(invoice=world["invoice"]).count() == 1


def test_customer_cannot_reissue(world):
    """Выпускает исполнитель: заказчик, вернувший акт, не выпускает его за продавца."""
    act = _rejected_act(world)

    resp = _api(world["buyer_user"]).post(f"/api/v1/crm/acts/{act.id}/reissue/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACT_ISSUER_SIDE_REQUIRED"


def test_issued_act_cannot_be_reissued(world):
    """Выпустить заново можно только возвращённый — не выпущенный и не подписанный."""
    _generate(world)
    act = Act.objects.get(invoice=world["invoice"])

    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/reissue/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACT_REISSUE_NOT_ALLOWED"


# ── Подсказка цепочки ───────────────────────────────────────────────────────


def test_chain_asks_to_reissue_instead_of_reporting_done(world):
    """Раньше наличие ЛЮБОГО акта гасило подсказку выпуска, и цепочка рапортовала «Завершено»
    по сделке, у которой живого закрывающего документа нет."""
    from crm.services.deal_documents import deal_document_hub

    act = _rejected_act(world)

    payload = deal_document_hub(world["deal"], world["seller_user"], None)

    assert payload["next_step"]["code"] == "REISSUE_ACT"
    assert payload["next_step"]["object_id"] == act.id


def test_cancelled_act_does_not_report_the_deal_as_done(world):
    from crm.services.deal_documents import deal_document_hub

    _generate(world)
    act = Act.objects.get(invoice=world["invoice"])
    _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/cancel/", {"reason": "ошибка"})

    payload = deal_document_hub(world["deal"], world["seller_user"], None)

    assert payload["next_step"]["code"] != "DONE", "аннулированный акт сделку не закрывает"
