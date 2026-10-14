"""W1 (spec-inbound-rfq-gap-analysis, утв. 27-07): email продавцу о новой заявке.

Паттерн instant-assign-notification (Odoo/Bitrix24/Salesforce): in-app колокольчик достигает
только залогиненных — email обязан долететь до оффлайн-продавца. Получатели — сотрудники своей
компании (продавец любой сделки, M1-ERP-02 волна 3); один task НА ПОЛУЧАТЕЛЯ — адреса не
встречаются в одном письме; участники других компаний писем не получают.
"""

from unittest.mock import patch

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage
from notifications.emails import _render_bodies
from notifications.models import NotificationType


@pytest.fixture
def world(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 20})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 1})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    own = Company.objects.create(name="Own Co", inn="3100000001")
    own.types.add(CompanyType.objects.get(code="SUPPLIER"))
    other = Company.objects.create(name="Other Client", inn="3100000002")
    other.types.add(CompanyType.objects.get(code="CLIENT"))

    def _member(company, email):
        user = CustomUser.objects.create_user(email=email, username=email, password="pw")
        CompanyMember.objects.create(
            user=user,
            company=company,
            role=WorkspaceRole.objects.get(code="OWNER"),
            is_active=True,
            can_sell=True,
        )
        return user

    user_a = _member(own, "a@sella.test")
    user_b = _member(own, "b@sellb.test")
    _member(other, "x@other.test")  # can_sell in ANOTHER company — not the back office
    buyer = Company.objects.create(name="ООО «Покупатель»", inn="7700000042")
    deal = Deal.objects.create(title="Рельсы Р65", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    return {"deal": deal, "user_a": user_a, "user_b": user_b, "own": own}


@pytest.mark.django_db(transaction=False)
def test_rfq_open_transition_emails_each_staff_member_separately(world, django_capture_on_commit_callbacks):
    deal = world["deal"]
    with patch("notifications.tasks.send_transactional_email.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            deal.stage = DealStage.objects.get(code="RFQ_OPEN")
            deal.save()
    # One task PER staff member — addresses never share a message; the outsider gets nothing.
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
def test_no_email_when_back_office_has_no_staff(world, django_capture_on_commit_callbacks):
    CompanyMember.objects.filter(company=world["own"]).update(is_active=False)
    buyer = Company.objects.create(name="Ещё покупатель", inn="7700000043")
    lone_deal = Deal.objects.create(title="X", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    with patch("notifications.tasks.send_transactional_email.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            lone_deal.stage = DealStage.objects.get(code="RFQ_OPEN")
            lone_deal.save()
    assert delay.call_count == 0  # сотрудников нет — писать некому


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
