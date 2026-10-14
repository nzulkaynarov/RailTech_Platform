"""WP-8 (P2-7 / P2-8): Russian pluralization of RFQ ActivityLog detail strings, and a
guard that the «Заявка отправлена поставщику (RFQ)» submit event is actually written to the
timeline (deal-linked ActivityLog) so the «История» feed can surface it.

The plural helper is pure (no DB). The submit test exercises the happy path of
``crm.services.rfq.submit_request`` end-to-end so the log row and its grammatical detail are
verified against the real service, not a fixture double.
"""

import pytest

from crm.services._plural import pluralize_ru

# ── P2-7: standard Slavic plural rule — one / few / many ──────────────────────────────────


def _positions(count):
    return pluralize_ru(count, "позиция", "позиции", "позиций")


def _sellers(count):
    # Dative case — «заявка адресована N продавцу/продавцам».
    return pluralize_ru(count, "продавцу", "продавцам", "продавцам")


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "позиция"),
        (2, "позиции"),
        (3, "позиции"),
        (4, "позиции"),
        (5, "позиций"),
        (0, "позиций"),
        (11, "позиций"),
        (12, "позиций"),
        (14, "позиций"),
        (21, "позиция"),
        (22, "позиции"),
        (25, "позиций"),
        (101, "позиция"),
        (111, "позиций"),
    ],
)
def test_pluralize_positions(count, expected):
    assert _positions(count) == expected


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "продавцу"),
        (2, "продавцам"),
        (5, "продавцам"),
        (11, "продавцам"),
        (21, "продавцу"),
    ],
)
def test_pluralize_sellers(count, expected):
    assert _sellers(count) == expected


def test_pluralize_negative_uses_absolute_value():
    # Defensive: a negative count must not fall through the modulo branches into `many`.
    assert _positions(-1) == "позиция"
    assert _positions(-2) == "позиции"


# ── P2-8: the submit-RFQ event lands on the deal timeline with a grammatical detail ───────


@pytest.fixture
def rfq_lookups(db):
    from accounts.models import CompanyType, WorkspaceRole
    from crm.models import DealStage, QuoteStatus

    for code in ["DRAFT", "RFQ_OPEN"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["CLIENT", "SUPPLIER"]:
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 1})
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 50})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 1})


def _make_buyer(company):
    from accounts.models import CompanyMember, CustomUser, WorkspaceRole

    user = CustomUser.objects.create_user(
        email=f"buyer{company.id}@t.test",
        username=f"buyer{company.id}@t.test",
        password="pw",
        is_active=True,
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        is_active=True,
        can_buy=True,
        is_primary=True,
    )
    return user


def _make_company(name, type_code):
    from accounts.models import Company, CompanyType

    company = Company.objects.create(
        name=name,
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


@pytest.mark.django_db
def test_submit_request_writes_deal_linked_activity_log(rfq_lookups):
    """A successful submit_request advances DRAFT → RFQ_OPEN and writes a deal-linked
    ActivityLog whose detail is grammatically pluralized. The deal FK is what the timeline
    endpoint (`crm/timeline/`, filter deal_id=…) scopes on, so its presence is the display
    layer's contract."""
    from crm.models import ActivityLog, Deal, DealSellerRouting, DealStage
    from crm.services.rfq import buyer_add_request_item, submit_request

    buyer_company = _make_company("Buyer Co", "CLIENT")
    seller_company = _make_company("Seller Co", "SUPPLIER")
    buyer = _make_buyer(buyer_company)
    deal = Deal.objects.create(title="RFQ", company=buyer_company, stage=DealStage.objects.get(code="DRAFT"))

    # Two distinct complete lines → len(items) == 2 → detail must read «2 позиции».
    buyer_add_request_item(buyer, deal, name="Рельс Р65", quantity=3)
    buyer_add_request_item(buyer, deal, name="Накладка 2Р65", quantity=1)
    # Free-text заявка has no product-implied routing; give it an explicit recipient so the
    # NO_RECIPIENTS guard passes and submit reaches RFQ_OPEN.
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_company)

    submitted = submit_request(buyer, deal)

    assert submitted.stage.code == "RFQ_OPEN"
    submit_logs = ActivityLog.objects.filter(deal=deal, action="Заявка отправлена поставщику (RFQ)")
    assert submit_logs.count() == 1, "submit event must be logged exactly once (no duplicate logging)"
    log = submit_logs.first()
    # deal FK populated → visible to the deal timeline (crm/timeline/ filters by deal_id).
    assert log.deal_id == deal.id
    assert log.detail.endswith("2 позиции"), log.detail
