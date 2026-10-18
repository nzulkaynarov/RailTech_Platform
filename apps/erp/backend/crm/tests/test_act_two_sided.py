"""Акт — двусторонний документ: выпускает исполнитель, принимает заказчик (G2).

Решение и его основания — `Docs/old/specs/spec-post-contract-open-questions-2026-07-30.md` §4.

Было: одно поле `signed_at`, НИ ОДНОГО подписанта и никакой проверки стороны — кто первый нажал,
тот и закрыл документ, включая того, кто его же и выпустил. Между тем акт двусторонний и в
узбекской практике («подтверждён двумя сторонами», ГК РУз ст. 646 привязывает возражения
заказчика к акту приёмки), и в российском ЭДО, где он состоит из двух титулов. Односторонняя
подпись — форма СЧЁТА, а не акта.

Стало: двухшаговый цикл по образцу ЭСФ — выпустил → принял или отклонил с причиной. Модель
скопирована с договора, где две подписи с подписантами уже были.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
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
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def act_world(lookups):
    buyer_co = _company("Buyer G2", "B200", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@g2.test")
    seller_co = _company("Seller G2", "S200", "SUPPLIER")
    seller_user = _member(seller_co, "seller@g2.test", can_sell=True)
    outsider = CustomUser.objects.create_user(email="outsider@g2.test", username="outsider@g2.test", password="x")

    deal = Deal.objects.create(title="G2 deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
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
#
# FIX-13: заказчика-пользователя в ERP нет — приёмка и отклонение акта живут в портале (FIX-22).
# Сервисы `sign_act` / `reject_act` остаются для него, но изнутри ERP не принимает никто, а
# эндпоинтов `acts/{id}/sign|reject` больше нет. Здесь закреплён главный инвариант двустороннего
# цикла: выпустивший акт не закрывает его сам, и несогласие без причины не принимается.


def test_the_issuer_cannot_accept_its_own_act(act_world):
    """ГЛАВНОЕ. Раньше выпустивший акт закрывал его сам — приёмка это подтверждение ВТОРОЙ
    стороны, иначе документ ничего не подтверждает."""
    from crm.services.billing import sign_act

    _act, error = sign_act(act_world["act"].id, act_world["seller_user"])

    assert error == "ACT_ACCEPTOR_SIDE_REQUIRED"
    act_world["act"].refresh_from_db()
    assert act_world["act"].status_code == "ISSUED", "акт закрыт выпустившей стороной"


def test_nobody_inside_erp_accepts_or_rejects_an_act(act_world):
    """Участник компании-клиента и посторонний не «заказчик» в ERP: ни принять, ни вернуть акт."""
    from crm.services.billing import reject_act, sign_act

    for actor in (act_world["buyer_user"], act_world["outsider"]):
        assert sign_act(act_world["act"].id, actor)[1] == "ACT_ACCEPTOR_SIDE_REQUIRED"
        assert reject_act(act_world["act"].id, actor, reason="Объём не совпадает")[1] == "ACT_ACCEPTOR_SIDE_REQUIRED"

    act_world["act"].refresh_from_db()
    assert act_world["act"].status_code == "ISSUED"
    assert act_world["act"].acceptor_signed_at is None


def test_rejection_without_a_reason_is_refused(act_world):
    """Причина обязательна — как и при отклонении КП: без основания отказ бесполезен."""
    from crm.services.billing import reject_act

    _act, error = reject_act(act_world["act"].id, act_world["buyer_user"], reason="   ")

    assert error == "REASON_REQUIRED"
    act_world["act"].refresh_from_db()
    assert act_world["act"].status_code == "ISSUED"


# ── Подсказки в API ──────────────────────────────────────────────────────────


def test_side_hints_offer_nothing_to_the_issuer(act_world):
    seller_row = _api(act_world["seller_user"]).get("/api/v1/crm/acts/").json()
    seller_act = (seller_row["results"] if isinstance(seller_row, dict) else seller_row)[0]
    assert seller_act["viewer_can_sign"] is False, "выпустившему предложили принять собственный акт"
    assert seller_act["viewer_can_reject"] is False


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
