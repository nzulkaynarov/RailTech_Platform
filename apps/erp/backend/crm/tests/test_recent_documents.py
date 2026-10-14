"""«Недавние документы» — the cross-type recent-documents dashboard feed
(GET /api/v1/crm/analytics/recent-documents/).

Covers: mixed types merged + date-desc sorted; per-type deep-link hash; the `limit`
clamp; and company-scoping — own-company staff (the seller of every deal, M1-ERP-02 wave 3)
and the buyer see their deal's documents, an outsider (a member of another client company) does
NOT, another company's DRAFT сгенерированный документ never leaks, and a non-member sees nothing.

Self-contained lookup seeding (CI runs --nomigrations)."""

from datetime import timedelta
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
    DocumentTemplate,
    DocumentTemplateKind,
    GeneratedDocument,
    GeneratedDocumentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)

URL = "/api/v1/crm/analytics/recent-documents/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="SIGNED", defaults={"name": "Signed", "sort_order": 10})
    for code in ("DRAFT", "ISSUED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    ActStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Issued", "sort_order": 10})
    DocumentTemplateKind.objects.get_or_create(code="LETTER", defaults={"name": "Письмо", "sort_order": 10})
    for code in ("DRAFT", "ISSUED"):
        GeneratedDocumentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name,
        inn=inn,
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


def _results(resp):
    assert resp.status_code == 200, resp.content
    return resp.json()["results"]


def _pairs(results):
    """Set of (type, id) tuples in a results payload."""
    return {(row["type"], row["id"]) for row in results}


@pytest.fixture
def world(lookups):
    """Buyer, own-company staff (the seller of every deal), an outsider from another client
    company, a platform admin, and a non-member."""
    buyer_co = _company("Buyer Co", "B100", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@rd.test", can_buy=True)

    seller_co = _company("Own Co", "S100", "SUPPLIER")
    seller_user = _member(seller_co, "seller@rd.test", can_sell=True)

    # An outsider — a member of ANOTHER client company: neither staff nor this deal's buyer.
    other_co = _company("Other Client Co", "O100", "CLIENT")
    other_user = _member(other_co, "other@rd.test", can_buy=True)

    admin_user = CustomUser.objects.create_user(
        is_superuser=True,
        email="admin@rd.test",
        username="admin@rd.test",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
    )
    nonmember_user = CustomUser.objects.create_user(
        email="nobody@rd.test", username="nobody@rd.test", password="x", role=SystemRole.objects.get(code="USER")
    )
    return {
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "seller_co": seller_co,
        "seller_user": seller_user,
        "other_co": other_co,
        "other_user": other_user,
        "admin_user": admin_user,
        "nonmember_user": nonmember_user,
    }


def _quote(deal, seller_co, seller_user, *, number="ACME-КП-2026-00001"):
    return Quote.objects.create(
        deal=deal,
        version=1,
        number=number,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=seller_user,
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )


@pytest.fixture
def docs(world):
    """A buyer-owned deal with the own company's КП, carrying one of every document type,
    plus another (client) company's DRAFT сгенерированный документ (must never leak). created_at is
    stamped in a deterministic ascending order so date-sort can be asserted."""
    deal = Deal.objects.create(title="Docs deal", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT"))
    quote = _quote(deal, world["seller_co"], world["seller_user"])

    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-2026-00001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-2026-00001",
        status=InvoiceStatus.objects.get(code="ISSUED"),
        total_incl_vat=Decimal("112"),
    )
    act = Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number="ACT-2026-00001",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )
    template = DocumentTemplate.objects.create(
        company=world["buyer_co"], name="Письмо", kind=DocumentTemplateKind.objects.get(code="LETTER")
    )
    generated = GeneratedDocument.objects.create(
        company=world["buyer_co"],
        deal=deal,
        template=template,
        number="DOC-2026-00001",
        title="Сопроводительное письмо",
        status=GeneratedDocumentStatus.objects.get(code="ISSUED"),
    )
    # Another company's private DRAFT letter on the deal — must never surface to buyer/staff.
    foreign_draft = GeneratedDocument.objects.create(
        company=world["other_co"],
        deal=deal,
        template=DocumentTemplate.objects.create(
            company=world["other_co"], name="Draft", kind=DocumentTemplateKind.objects.get(code="LETTER")
        ),
        number="DOC-OTHER-00001",
        title="Секрет чужой компании",
        status=GeneratedDocumentStatus.objects.get(code="DRAFT"),
    )

    # Deterministic ascending created_at (quote oldest → generated newest) so the feed's
    # date-desc order is assertable despite auto_now_add stamping near-identical times.
    base = timezone.now() - timedelta(hours=10)
    for offset, (model, obj) in enumerate(
        [(Quote, quote), (Contract, contract), (Invoice, invoice), (Act, act), (GeneratedDocument, generated)]
    ):
        model.objects.filter(pk=obj.pk).update(created_at=base + timedelta(hours=offset))

    return {
        "deal": deal,
        "quote": quote,
        "contract": contract,
        "invoice": invoice,
        "act": act,
        "generated": generated,
        "foreign_draft": foreign_draft,
    }


# ── 1. Mixed types, merged + sorted date-desc ─────────────────────────────────


def test_returns_all_types_sorted_desc(world, docs):
    results = _results(_api(world["buyer_user"]).get(URL))
    assert _pairs(results) >= {
        ("quote", docs["quote"].id),
        ("contract", docs["contract"].id),
        ("invoice", docs["invoice"].id),
        ("act", docs["act"].id),
        ("generated", docs["generated"].id),
    }
    dates = [row["date"] for row in results]
    assert dates == sorted(dates, reverse=True), "feed must be sorted by date descending"
    # Newest created (generated) first, oldest (quote) last among our five.
    assert results[0]["type"] == "generated"


# ── 2. Фид отдаёт данные для маршрута, но не сам маршрут ──────────────────────


def test_feed_carries_routing_inputs_and_no_spa_route(world, docs):
    """Каждая строка несёт `type`/`id`/`deal` — этого фронту хватает, чтобы вычислить маршрут
    по стороне зрителя. Готового `hash` здесь больше нет: он был продавцовским для акта и КП и
    уводил покупателя в отказ (аудит UI 2026-07-30). Возврат поля ломает этот тест."""
    rows = _results(_api(world["buyer_user"]).get(URL))
    assert rows, "фид не должен быть пустым"
    for row in rows:
        assert "hash" not in row, "маршрут SPA считает фронт, бэкенд про его гейты не знает"
        assert row["type"] and row["id"]
        assert "deal" in row


def test_payload_fields_shape(world, docs):
    row = next(r for r in _results(_api(world["buyer_user"]).get(URL)) if r["type"] == "generated")
    assert row["label"] == "Сопроводительное письмо"  # title wins over number
    assert row["status_code"] == "ISSUED"
    assert row["deal"] == docs["deal"].id


# ── 3. limit clamp (1..20, default 8) ─────────────────────────────────────────


def test_limit_respected(world, docs):
    assert len(_results(_api(world["buyer_user"]).get(URL, {"limit": 2}))) == 2


def test_limit_clamped_low_and_high_and_invalid(world, docs):
    # 0 → clamped up to 1.
    assert len(_results(_api(world["buyer_user"]).get(URL, {"limit": 0}))) == 1
    # 100 → clamped down to 20 max; we have 5 visible → 5, and no error.
    assert len(_results(_api(world["buyer_user"]).get(URL, {"limit": 100}))) == 5
    # garbage → default 8; we have 5 visible → 5.
    assert len(_results(_api(world["buyer_user"]).get(URL, {"limit": "abc"}))) == 5


# ── 4. Company-scope: staff and buyer see, an outsider and a non-member do not ──


def _our(docs):
    return {
        ("quote", docs["quote"].id),
        ("contract", docs["contract"].id),
        ("invoice", docs["invoice"].id),
        ("act", docs["act"].id),
        ("generated", docs["generated"].id),
    }


def test_staff_sees_every_deal_document(world, docs):
    """The seller of every deal is the own company: its staff see the КП and the billing chain
    exactly like the КП / billing viewsets show them (and the client's ISSUED letter)."""
    pairs = _pairs(_results(_api(world["seller_user"]).get(URL)))
    assert pairs >= _our(docs)


def test_buyer_sees_own_deal_documents(world, docs):
    pairs = _pairs(_results(_api(world["buyer_user"]).get(URL)))
    assert pairs >= _our(docs)


def test_outsider_sees_none_of_the_deal_documents(world, docs):
    pairs = _pairs(_results(_api(world["other_user"]).get(URL)))
    assert pairs.isdisjoint(_our(docs)), "an outsider saw the deal's documents"


def test_foreign_draft_generated_never_leaks(world, docs):
    """Another company's DRAFT letter is its private working copy — the same rule as
    GeneratedDocumentViewSet (own company any status + counterparties' ISSUED only)."""
    foreign = ("generated", docs["foreign_draft"].id)
    for viewer in ("buyer_user", "seller_user"):
        pairs = _pairs(_results(_api(world[viewer]).get(URL)))
        assert foreign not in pairs, f"foreign DRAFT letter leaked to {viewer}"


def test_non_member_sees_nothing(world, docs):
    assert _results(_api(world["nonmember_user"]).get(URL)) == []


def test_platform_admin_sees_all_types(world, docs):
    pairs = _pairs(_results(_api(world["admin_user"]).get(URL)))
    assert pairs >= _our(docs)
