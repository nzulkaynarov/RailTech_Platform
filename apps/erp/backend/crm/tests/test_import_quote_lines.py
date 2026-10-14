"""Q2 (станция КП): импорт позиций КП из файла продавцом — worker-safe вставка.

Продавец грузит файл (Excel/PDF/фото) в КП; AI-экстрактор (переиспользован из покупательского
флоу) отдаёт строки, import_extracted_lines_into_quote вставляет их в КОНКРЕТНЫЙ КП. Здесь —
детерминированная часть (вставка + гейты); AI-извлечение мокается.
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.quotes.bulk import import_extracted_lines_into_quote
from master_data.models import Currency


@pytest.fixture
def scene(db):
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$", "sort_order": 10})[0]
    DealStage.objects.get_or_create(code="CALCULATING", defaults={"name": "Расчёт", "sort_order": 50})
    draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]

    buyer = Company.objects.create(name="Buyer", inn="7710009001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Seller", inn="3310009001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    # Посторонний — участник ДРУГОЙ (клиентской) компании с правом цены в ней: не сотрудник своей.
    other = Company.objects.create(name="Other", inn="3310009002")
    other.types.add(CompanyType.objects.get(code="CLIENT"))

    role = CompanyRole.objects.create(company=seller, name="М", permissions=["quote.edit_pricing"])
    ws = WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "SM", "sort_order": 10})[0]

    def _member(company, email):
        r = CompanyRole.objects.get_or_create(
            company=company, name="М", defaults={"permissions": ["quote.edit_pricing"]}
        )[0]
        user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
        CompanyMember.objects.create(
            user=user, company=company, role=ws, company_role=r, is_active=True, is_primary=True, can_sell=True
        )
        return user

    seller_user = _member(seller, "s@s.uz")
    other_user = _member(other, "o@o.uz")

    deal = Deal.objects.create(title="D", company=buyer, stage=DealStage.objects.get(code="CALCULATING"))
    quote = Quote.objects.create(
        deal=deal, version=1, status=draft, prepared_by=seller_user, seller_company=seller, cost_currency_default=usd
    )
    QuoteItem.objects.create(quote=quote, imported_raw_name="Старая строка", quantity=1, position=1)
    return locals()


_ROWS = [
    {"name": "Рельс Р65", "quantity": 100, "unit": "шт.", "gost_drawing": "ГОСТ Р 51685"},
    {"name": "  ", "quantity": 5},  # пустое имя → отбрасывается
    {"name": "Накладка", "quantity": "50", "mpn": "2726", "name_canonical": "НАКЛАДКА"},
]


@pytest.mark.django_db
def test_import_appends_lines_after_existing_with_default_currency(scene):
    added, truncated, err = import_extracted_lines_into_quote(scene["quote"], scene["seller_user"], _ROWS)
    assert err is None and added == 2 and truncated is False
    scene["quote"].refresh_from_db()
    items = list(scene["quote"].items.order_by("position"))
    assert [i.imported_raw_name for i in items] == ["Старая строка", "Рельс Р65", "Накладка"]  # в конец
    rail = items[1]
    assert rail.quantity == 100 and rail.gost_drawing == "ГОСТ Р 51685"
    assert rail.frozen_currency.code == "USD"  # валюта себестоимости КП (как ручное добавление)
    assert items[2].mpn == "2726" and items[2].name_canonical == "НАКЛАДКА"


@pytest.mark.django_db
def test_import_rejected_for_outsider(scene):
    added, _t, err = import_extracted_lines_into_quote(scene["quote"], scene["other_user"], _ROWS)
    # Право цены — только в своей компании; роль в чужой компании ничего не даёт.
    assert added == 0 and err == "ONLY_SELLER_CAN_BUILD_QUOTE"
    assert scene["quote"].items.count() == 1


@pytest.mark.django_db
def test_import_rejected_on_frozen_quote(scene):
    from django.utils import timezone

    scene["quote"].frozen_at = timezone.now()
    scene["quote"].save()
    added, _t, err = import_extracted_lines_into_quote(scene["quote"], scene["seller_user"], _ROWS)
    assert added == 0 and err == "QUOTE_FROZEN"


@pytest.mark.django_db
def test_import_truncates_over_limit_and_reports(scene, settings):
    settings.QUOTE_ITEMS_BULK_MAX_ROWS = 3
    rows = [{"name": f"Позиция {i}", "quantity": 1} for i in range(5)]
    added, truncated, err = import_extracted_lines_into_quote(scene["quote"], scene["seller_user"], rows)
    assert err is None and added == 3 and truncated is True  # тупик №8: обрезание НЕ молча


@pytest.mark.django_db
def test_import_no_lines_returns_code(scene):
    added, _t, err = import_extracted_lines_into_quote(scene["quote"], scene["seller_user"], [{"name": ""}, {}])
    assert added == 0 and err == "IMPORT_NO_LINES"
