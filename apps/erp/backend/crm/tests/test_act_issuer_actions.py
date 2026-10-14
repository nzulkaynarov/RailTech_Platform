"""Действия ВЫПУСТИВШЕЙ стороны по акту: напомнить и аннулировать (A4).

Двусторонний цикл (G2) дал заказчику два ответа — принять или вернуть с причиной, — но у
исполнителя после выпуска не осталось ничего: акт висел, и сделать с ним было нечего.

Оба действия скопированы с эталонов закрывающих документов, и тесты закрепляют именно те
свойства, ради которых эталон так устроен:

* **напоминание** — повтор УЖЕ существующего приглашения (Resend у DocuSign), не чаще раза в
  сутки на документ (manual reminder у PandaDoc). Число писем на отрезке остаётся прежним —
  канон «ровно четыре» не нарушен;
* **аннулирование** — только выпустившей стороной, причина обязательна и уходит адресату,
  статус терминальный: «unvoid» не существует ни у DocuSign, ни у Adobe Acrobat Sign.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
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


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(db, grant):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code, name in (("CLIENT", "Client"), ("SUPPLIER", "Supplier")):
        CompanyType.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})

    def company(name, inn, type_code):
        obj = Company.objects.create(name=name, inn=inn)
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

    buyer_co = company("Buyer A4", "B400", "CLIENT")
    buyer_user = member(buyer_co, "buyer@a4.test", can_buy=True, can_sell=False)
    seller_co = company("Seller A4", "S400", "SUPPLIER")
    seller_user = member(seller_co, "seller@a4.test", can_sell=True, can_buy=False)
    grant(seller_user, "fulfillment.act")

    deal = Deal.objects.create(title="A4 deal", company=buyer_co, stage=DealStage.objects.get(code="CLOSED_WON"))
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
        number="CT-A4-001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-A4-001",
        status=InvoiceStatus.objects.get(code="PAID"),
        total_incl_vat=Decimal("112"),
        amount_paid=Decimal("112"),
    )
    act = Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number="ACT-A4-001",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
        created_by=seller_user,
        issuer_signer=seller_user,
        issuer_signed_at=timezone.now(),
    )
    return {"act": act, "deal": deal, "buyer_user": buyer_user, "seller_user": seller_user}


# ── Напоминание ──────────────────────────────────────────────────────────────


def test_issuer_reminds_the_customer(world):
    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{world['act'].id}/remind/")

    assert resp.status_code == 200, resp.content
    world["act"].refresh_from_db()
    assert world["act"].reminder_sent_at is not None, "факт напоминания должен сохраняться"
    assert world["act"].status_code == "ISSUED", "напоминание не меняет состояние документа"


def test_second_reminder_within_24h_is_refused(world):
    """Ограничение частоты — не косметика: доставляемость считается по домену целиком, и
    мусорные письма бьют по критичным (порог жалоб Google/Yahoo 0,3%)."""
    api = _api(world["seller_user"])
    assert api.post(f"/api/v1/crm/acts/{world['act'].id}/remind/").status_code == 200

    resp = api.post(f"/api/v1/crm/acts/{world['act'].id}/remind/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACT_REMINDER_TOO_SOON"


def test_reminder_is_allowed_again_after_the_cooldown(world):
    act = world["act"]
    act.reminder_sent_at = timezone.now() - timedelta(hours=25)
    act.save(update_fields=["reminder_sent_at"])

    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/remind/")

    assert resp.status_code == 200, resp.content


def test_customer_cannot_remind_itself(world):
    """Напоминает тот, кто ЖДЁТ ответа. Заказчику напоминать некому — ход его собственный.
    M1-ERP-05: напоминание — право бэк-офиса `fulfillment.act`, покупатель отсекается гейтом."""
    resp = _api(world["buyer_user"]).post(f"/api/v1/crm/acts/{world['act'].id}/remind/")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"


def test_no_reminder_for_a_settled_act(world):
    act = world["act"]
    act.status = ActStatus.objects.get(code="SIGNED")
    act.save(update_fields=["status"])

    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/remind/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACT_REMINDER_NOT_ALLOWED"


def test_reminder_reuses_the_existing_invitation_and_adds_no_new_email_kind(world, mailoutbox):
    """Канон отрезка: писем ровно четыре. Напоминание — ПОВТОР приглашения, а не пятый вид."""
    _api(world["seller_user"]).post(f"/api/v1/crm/acts/{world['act'].id}/remind/")

    from notifications.models import EmailLog

    templates = set(EmailLog.objects.values_list("template", flat=True))
    assert templates <= {"act_awaiting_acceptance"}, f"появился новый вид письма: {templates}"


# ── Аннулирование ────────────────────────────────────────────────────────────


def test_issuer_cancels_its_own_act_with_a_reason(world):
    resp = _api(world["seller_user"]).post(
        f"/api/v1/crm/acts/{world['act'].id}/cancel/",
        {"reason": "выставлен по ошибке, объём уточняется"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    world["act"].refresh_from_db()
    assert world["act"].status_code == "CANCELLED"
    assert "по ошибке" in world["act"].cancellation_reason


def test_cancellation_without_a_reason_is_refused(world):
    """Без основания отзыв выглядит для заказчика как сбой, а не как решение контрагента."""
    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{world['act'].id}/cancel/", {}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "REASON_REQUIRED"


def test_customer_cannot_cancel_the_act(world):
    """Отзывает только ВЫПУСТИВШАЯ сторона (у DocuSign и Adobe — тоже только отправитель).
    Ответ заказчика называется «вернуть с причиной» и живёт в отдельном экшене."""
    resp = _api(world["buyer_user"]).post(
        f"/api/v1/crm/acts/{world['act'].id}/cancel/", {"reason": "не хочу"}, format="json"
    )

    # M1-ERP-05: аннулирование — право бэк-офиса `fulfillment.act`; покупателя отсекает гейт.
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"


def test_a_settled_act_cannot_be_cancelled(world):
    """Согласованный обеими сторонами документ не «разподписывают»: его судьбу решает новый акт."""
    act = world["act"]
    act.status = ActStatus.objects.get(code="SIGNED")
    act.acceptor_signer = world["buyer_user"]
    act.acceptor_signed_at = timezone.now()
    act.save(update_fields=["status", "acceptor_signer", "acceptor_signed_at"])

    resp = _api(world["seller_user"]).post(f"/api/v1/crm/acts/{act.id}/cancel/", {"reason": "передумал"}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACT_CANCEL_NOT_ALLOWED"


def test_cancellation_is_terminal(world):
    """«Unvoid» не существует: повторное действие по отозванному акту отказывает."""
    api = _api(world["seller_user"])
    api.post(f"/api/v1/crm/acts/{world['act'].id}/cancel/", {"reason": "ошибка"}, format="json")

    resp = api.post(f"/api/v1/crm/acts/{world['act'].id}/cancel/", {"reason": "ещё раз"}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACT_CANCEL_NOT_ALLOWED"


# ── Подсказки совпадают с сервисами ──────────────────────────────────────────


def test_hints_match_what_the_services_actually_allow(world):
    """Кнопка не должна появляться там, где действие откажет, и наоборот."""
    seller_view = _api(world["seller_user"]).get(f"/api/v1/crm/acts/{world['act'].id}/").json()
    buyer_view = _api(world["buyer_user"]).get(f"/api/v1/crm/acts/{world['act'].id}/").json()

    assert seller_view["viewer_can_remind"] is True and seller_view["viewer_can_cancel"] is True
    assert seller_view["viewer_can_sign"] is False, "выпустивший не принимает свой же акт"
    assert buyer_view["viewer_can_remind"] is False and buyer_view["viewer_can_cancel"] is False
    assert buyer_view["viewer_can_sign"] is True


def test_reminder_hint_goes_dark_during_the_cooldown(world):
    """Кулдаун виден заранее, а не выясняется отказом после нажатия."""
    api = _api(world["seller_user"])
    api.post(f"/api/v1/crm/acts/{world['act'].id}/remind/")

    view = api.get(f"/api/v1/crm/acts/{world['act'].id}/").json()

    assert view["viewer_can_remind"] is False
    assert view["reminder_sent_at"] is not None
