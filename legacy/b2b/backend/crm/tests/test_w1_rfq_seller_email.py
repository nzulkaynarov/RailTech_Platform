"""W1 (spec-inbound-rfq-gap-analysis, утв. 27-07): email продавцу о новой заявке.

Паттерн instant-assign-notification (Odoo/Bitrix24/Salesforce): in-app колокольчик достигает
только залогиненных — email обязан долететь до оффлайн-продавца. Один task НА ПОЛУЧАТЕЛЯ:
routed-компании — конкуренты, их адреса не должны встречаться в одном письме.
"""

from unittest.mock import patch

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealSellerRouting, DealStage
from notifications.emails import _render_bodies
from notifications.models import NotificationType


@pytest.fixture
def world(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 20})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 1})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})

    def _seller(name, inn, email):
        company = Company.objects.create(name=name, inn=inn)
        company.types.add(CompanyType.objects.get(code="SUPPLIER"))
        user = CustomUser.objects.create_user(email=email, username=email, password="pw")
        CompanyMember.objects.create(
            user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"),
            is_active=True, can_sell=True,
        )
        return company, user

    seller_a, user_a = _seller("Seller A", "3100000001", "a@sella.test")
    seller_b, user_b = _seller("Seller B", "3100000002", "b@sellb.test")
    buyer = Company.objects.create(name="ООО «Покупатель»", inn="7700000042")
    deal = Deal.objects.create(
        title="Рельсы Р65", company=buyer, stage=DealStage.objects.get(code="DRAFT")
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_a)
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_b)
    return {"deal": deal, "user_a": user_a, "user_b": user_b}


@pytest.mark.django_db(transaction=False)
def test_rfq_open_transition_emails_each_routed_seller_separately(world, django_capture_on_commit_callbacks):
    deal = world["deal"]
    with patch("notifications.tasks.send_transactional_email.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            deal.stage = DealStage.objects.get(code="RFQ_OPEN")
            deal.save()
    # One task PER recipient — competitor addresses never share a message.
    assert delay.call_count == 2
    recipients = sorted(call.kwargs["to"][0] for call in delay.call_args_list)
    assert recipients == ["a@sella.test", "b@sellb.test"]
    for call in delay.call_args_list:
        assert call.args[0] == "new_rfq_seller"
        context = call.args[1]
        assert context["buyer_name"] == "ООО «Покупатель»"
        assert context["deal_url"].endswith(f"#request-detail/{deal.pk}")
        assert len(call.kwargs["to"]) == 1


@pytest.mark.django_db(transaction=False)
def test_no_email_without_routing(world, django_capture_on_commit_callbacks):
    buyer = Company.objects.create(name="Ещё покупатель", inn="7700000043")
    lone_deal = Deal.objects.create(title="X", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    with patch("notifications.tasks.send_transactional_email.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            lone_deal.stage = DealStage.objects.get(code="RFQ_OPEN")
            lone_deal.save()
    assert delay.call_count == 0  # никому не роутили — никому не пишем


@pytest.mark.django_db
def test_new_rfq_seller_template_renders_link_and_buyer():
    subject, text, html = _render_bodies(
        "new_rfq_seller",
        {
            "buyer_name": "ООО «Покупатель»",
            "deal_title": "Рельсы Р65",
            "deal_url": "https://b2b.railtech.uz/#request-detail/42",
            "assigned": False,
        },
    )
    assert "Новая заявка" in subject and "ООО «Покупатель»" in subject
    for body in (text, html):
        assert "https://b2b.railtech.uz/#request-detail/42" in body
        assert "Рельсы Р65" in body
    # Платформенный бренд (внутреннее письмо продавцу) — white-label здесь не применяется.
    assert "RailTech B2B" in html


@pytest.mark.django_db
def test_assigned_variant_says_personally_assigned():
    _s, text, html = _render_bodies(
        "new_rfq_seller",
        {"buyer_name": "B", "deal_title": "", "deal_url": "https://x/#request-detail/1", "assigned": True},
    )
    assert "назначена лично вам" in text and "назначена лично вам" in html
