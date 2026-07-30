"""Акт — двусторонний документ: выпускает исполнитель, принимает заказчик (G2).

Решение и его основания — `Docs/dev/specs/spec-post-contract-open-questions-2026-07-30.md` §4.

Было: одно поле `signed_at`, НИ ОДНОГО подписанта и никакой проверки стороны — кто первый нажал,
тот и закрыл документ, включая того, кто его же и выпустил. Между тем акт двусторонний и в
узбекской практике («подтверждён двумя сторонами», ГК РУз ст. 646 привязывает возражения
заказчика к акту приёмки), и в российском ЭДО, где он состоит из двух титулов. Односторонняя
подпись — форма СЧЁТА, а не акта.

Стало: двухшаговый цикл по образцу ЭСФ — выпустил → принял или отклонил с причиной. Модель
скопирована с договора, где две подписи с подписантами уже были.
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
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import (
    Act,
    ActStatus,
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


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    for code in ("USER", "ADMIN"):
        SystemRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 80})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 50})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 40})
    for code in ("DRAFT", "ISSUED", "PAID", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    from notifications.models import NotificationType

    for code in ("INFO", "SUCCESS", "WARNING"):
        NotificationType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def act_world(lookups):
    buyer_co = _company("Buyer G2", "B200", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@g2.test", can_buy=True)
    seller_co = _company("Seller G2", "S200", "SUPPLIER")
    seller_user = _member(seller_co, "seller@g2.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=seller_co, plan="PREMIUM", status="ACTIVE", valid_until=timezone.now().date() + timedelta(days=30)
    )
    outsider = CustomUser.objects.create_user(email="outsider@g2.test", username="outsider@g2.test", password="x")

    deal = Deal.objects.create(title="G2 deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
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
        number="CT-G2-001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-G2-001",
        status=InvoiceStatus.objects.get(code="PAID"),
        total_incl_vat=Decimal("112"),
        amount_paid=Decimal("112"),
    )
    act = Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number="ACT-G2-001",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
        created_by=seller_user,
        issuer_signer=seller_user,
        issuer_signed_at=timezone.now(),
    )
    return {
        "deal": deal,
        "act": act,
        "invoice": invoice,
        "buyer_user": buyer_user,
        "seller_user": seller_user,
        "outsider": outsider,
    }


# ── Кто может закрыть акт ────────────────────────────────────────────────────


def test_buyer_accepts_the_act(act_world):
    resp = _api(act_world["buyer_user"]).post(f"/api/v1/crm/acts/{act_world['act'].id}/sign/")

    assert resp.status_code == 200, resp.content
    act = act_world["act"]
    act.refresh_from_db()
    assert act.status_code == "SIGNED"
    assert act.acceptor_signer_id == act_world["buyer_user"].id, "подписант приёмки не сохранён"
    assert act.acceptor_signed_at is not None
    assert act.issuer_signer_id == act_world["seller_user"].id, "титул исполнителя должен уцелеть"
    assert act.is_fully_signed is True


def test_the_issuer_cannot_accept_its_own_act(act_world):
    """ГЛАВНОЕ. Раньше выпустивший акт закрывал его сам — приёмка это подтверждение ВТОРОЙ
    стороны, иначе документ ничего не подтверждает."""
    resp = _api(act_world["seller_user"]).post(f"/api/v1/crm/acts/{act_world['act'].id}/sign/")

    assert resp.status_code == 400, resp.content
    assert resp.json()["detail"] == "ACT_ACCEPTOR_SIDE_REQUIRED"
    act_world["act"].refresh_from_db()
    assert act_world["act"].status_code == "ISSUED", "акт закрыт выпустившей стороной"


def test_an_outsider_cannot_touch_the_act(act_world):
    """Граница арендатора держится и на новом экшене.

    `sign` принимает multipart (туда грузят скан), `reject` — JSON, поэтому вызовы разные.
    """
    outsider = _api(act_world["outsider"])
    act_id = act_world["act"].id

    signed = outsider.post(f"/api/v1/crm/acts/{act_id}/sign/")
    assert signed.status_code in (400, 403, 404), signed.status_code

    rejected = outsider.post(f"/api/v1/crm/acts/{act_id}/reject/", {"reason": "нет"}, format="json")
    assert rejected.status_code in (400, 403, 404), rejected.status_code

    act_world["act"].refresh_from_db()
    assert act_world["act"].status_code == "ISSUED"


# ── Отклонение — второй шаг, которого не было ────────────────────────────────


def test_buyer_rejects_the_act_with_a_reason(act_world):
    resp = _api(act_world["buyer_user"]).post(
        f"/api/v1/crm/acts/{act_world['act'].id}/reject/",
        {"reason": "Объём работ не совпадает с накладной"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    act = act_world["act"]
    act.refresh_from_db()
    assert act.status_code == "DRAFT", "отклонённый акт возвращается исполнителю на доработку"
    assert act.rejection_reason == "Объём работ не совпадает с накладной"
    assert act.acceptor_signed_at is None, "отклонение — не приёмка"


def test_rejection_without_a_reason_is_refused(act_world):
    """Причина обязательна — как и при отклонении КП: без основания отказ бесполезен."""
    resp = _api(act_world["buyer_user"]).post(
        f"/api/v1/crm/acts/{act_world['act'].id}/reject/", {"reason": "   "}, format="json"
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "REASON_REQUIRED"
    act_world["act"].refresh_from_db()
    assert act_world["act"].status_code == "ISSUED"


def test_seller_is_notified_about_the_rejection(act_world, django_capture_on_commit_callbacks):
    """Отказ не должен быть тише согласия."""
    from notifications.models import Notification

    with django_capture_on_commit_callbacks(execute=True):
        _api(act_world["buyer_user"]).post(
            f"/api/v1/crm/acts/{act_world['act'].id}/reject/", {"reason": "Нет подписи прораба"}, format="json"
        )

    titles = list(Notification.objects.filter(user=act_world["seller_user"]).values_list("title", flat=True))
    assert "Акт отклонён заказчиком" in titles


def test_a_rejected_act_can_be_reissued_and_then_accepted(act_world):
    """Цикл замыкается: исполнитель правит и выставляет заново, заказчик принимает."""
    buyer = _api(act_world["buyer_user"])
    buyer.post(f"/api/v1/crm/acts/{act_world['act'].id}/reject/", {"reason": "исправьте объём"}, format="json")

    act = act_world["act"]
    act.refresh_from_db()
    act.status = ActStatus.objects.get(code="ISSUED")
    act.issuer_signed_at = timezone.now()
    act.save(update_fields=["status", "issuer_signed_at"])

    resp = buyer.post(f"/api/v1/crm/acts/{act.id}/sign/")

    assert resp.status_code == 200, resp.content
    act.refresh_from_db()
    assert act.status_code == "SIGNED"
    assert act.is_fully_signed is True


# ── Подсказки в API адресны ──────────────────────────────────────────────────


def test_side_hints_are_addressed_to_the_acceptor_only(act_world):
    buyer_row = _api(act_world["buyer_user"]).get("/api/v1/crm/acts/").json()
    buyer_act = (buyer_row["results"] if isinstance(buyer_row, dict) else buyer_row)[0]
    assert buyer_act["viewer_can_sign"] is True
    assert buyer_act["viewer_can_reject"] is True

    seller_row = _api(act_world["seller_user"]).get("/api/v1/crm/acts/").json()
    seller_act = (seller_row["results"] if isinstance(seller_row, dict) else seller_row)[0]
    assert seller_act["viewer_can_sign"] is False, "выпустившему предложили принять собственный акт"
    assert seller_act["viewer_can_reject"] is False


def test_signed_act_offers_nothing_further(act_world):
    _api(act_world["buyer_user"]).post(f"/api/v1/crm/acts/{act_world['act'].id}/sign/")

    rows = _api(act_world["buyer_user"]).get("/api/v1/crm/acts/").json()
    row = (rows["results"] if isinstance(rows, dict) else rows)[0]
    assert row["viewer_can_sign"] is False
    assert row["viewer_can_reject"] is False
    assert row["acceptor_signer_name"] is not None, "в ответе должно быть видно, кто принял"


def test_generated_act_records_its_issuer(act_world):
    """Выпуск — первый титул: раньше по документу нельзя было сказать, кто его выставил."""
    from crm.services.billing import generate_act

    act_world["act"].status = ActStatus.objects.get(code="CANCELLED")
    act_world["act"].save(update_fields=["status"])

    fresh, error = generate_act(act_world["invoice"].id, actor=act_world["seller_user"])

    assert error is None, error
    assert fresh.issuer_signer_id == act_world["seller_user"].id
    assert fresh.issuer_signed_at is not None
    assert fresh.acceptor_signed_at is None, "свежий акт ещё никем не принят"
