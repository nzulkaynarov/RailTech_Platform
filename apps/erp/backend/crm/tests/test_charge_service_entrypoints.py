"""Точки входа сервиса расходов: смена базиса поставки и порядок каскада.

`apply_charge_template_to_quote` покрыт в `test_quote_charges.py`, а вот обе ФУНКЦИИ,
через которые продавец реально меняет деньги в КП, не были покрыты вовсе (41% файла,
непокрытые строки 79-100 и 111-148). Это гейты прав, защита замороженного КП и — главное —
логика KP-05, ОДНАЖДЫ УЖЕ ЧИНЕННАЯ. Комментарий в коде говорит прямо: иначе фрахт EXW
остаётся после переключения на DDP и молча раздувает итог. Без теста такое регрессирует
незаметно: неверная сумма уходит клиенту в подписанном документе.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import ChargeTemplate, ChargeType, Deal, DealStage, Quote, QuoteCharge, QuoteItem, QuoteStatus
from crm.services.charges import reorder_quote_charges, set_quote_delivery_basis
from master_data.models import Country, DeliveryBasis


@pytest.fixture(autouse=True)
def _isolate_seeded_charge_templates(db):
    """Профили Incoterm — сид-данные (миграция crm/0036). Тесты считают точные количества,
    поэтому глобальный сид убирается (откатывается вместе с транзакцией теста)."""
    ChargeTemplate.objects.filter(company__isnull=True).delete()


@pytest.fixture
def world(db):
    """Продавец, покупатель, КП-черновик и два базиса поставки со своими шаблонами."""
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "DRAFT", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    uzbekistan = Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})[0]

    seller_company = Company.objects.create(name="Продавец", inn="1000000001")
    seller_company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = CustomUser.objects.create_user(
        email="seller@charges.test", username="charges_seller", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=seller,
        company=seller_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )

    buyer_company = Company.objects.create(name="Покупатель", inn="2000000002")
    buyer_company.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer = CustomUser.objects.create_user(
        email="buyer@charges.test", username="charges_buyer", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=buyer,
        company=buyer_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
    )

    deal = Deal.objects.create(
        title="Сделка", company=buyer_company, client=buyer, stage=DealStage.objects.get(code="DRAFT")
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=seller,
        tax_country=uzbekistan,
        vat_rate=Decimal("12.00"),
    )
    QuoteItem.objects.create(quote=quote, frozen_base_price=Decimal("100.00"), quantity=1)
    quote.refresh_from_db()

    exw = DeliveryBasis.objects.get_or_create(code="EXW", defaults={"name": "EXW", "sort_order": 10})[0]
    ddp = DeliveryBasis.objects.get_or_create(code="DDP", defaults={"name": "DDP", "sort_order": 20})[0]
    freight = ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Фрахт", "sort_order": 10})[0]
    insurance = ChargeType.objects.get_or_create(code="INSURANCE", defaults={"name": "Страховка", "sort_order": 20})[0]
    ChargeTemplate.objects.create(
        company=seller_company, delivery_basis=exw, charge_type=freight, default_amount=Decimal("50.00"), is_active=True
    )
    ChargeTemplate.objects.create(
        company=seller_company,
        delivery_basis=ddp,
        charge_type=insurance,
        default_amount=Decimal("30.00"),
        is_active=True,
    )

    return {
        "seller": seller,
        "seller_company": seller_company,
        "buyer": buyer,
        "quote": quote,
        "exw": exw,
        "ddp": ddp,
        "freight": freight,
        "insurance": insurance,
    }


def _charge_codes(quote) -> set:
    return set(quote.charges.values_list("charge_type__code", flat=True))


# ── Гейты: кто вообще имеет право менять деньги в КП ──────────────────────────


@pytest.mark.django_db
class TestSetDeliveryBasisGates:
    def test_buyer_cannot_build_quote(self, world):
        quote, error = set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["buyer"])
        assert quote is None
        assert error == "ONLY_SELLER_CAN_BUILD_QUOTE"

    def test_frozen_quote_is_locked(self, world):
        """Отправленное КП заморожено: менять базис (а значит и сумму) уже нельзя."""
        from django.utils import timezone

        world["quote"].frozen_at = timezone.now()
        world["quote"].save(update_fields=["frozen_at"])
        quote, error = set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        assert quote is None
        assert error == "QUOTE_FROZEN"

    def test_unknown_basis_is_rejected(self, world):
        quote, error = set_quote_delivery_basis(world["quote"].id, 10**7, world["seller"])
        assert quote is None
        assert error == "DELIVERY_BASIS_NOT_FOUND"


# ── KP-05: смена базиса не должна оставлять чужие авто-расходы ────────────────


@pytest.mark.django_db
class TestBasisChangeDropsStaleTemplateRows:
    def test_switching_basis_removes_previous_template_rows(self, world):
        """ГЛАВНЫЙ регресс-тест. EXW заводит фрахт; после переключения на DDP фрахта быть
        не должно — иначе он молча остаётся в итоге, и клиент получает завышенную сумму."""
        quote, error = set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        assert error is None
        assert _charge_codes(quote) == {"FREIGHT"}

        quote, error = set_quote_delivery_basis(world["quote"].id, world["ddp"].id, world["seller"])
        assert error is None
        assert _charge_codes(quote) == {"INSURANCE"}, "фрахт EXW пережил переключение на DDP"

    def test_totals_follow_the_new_basis(self, world):
        """Сумма — это то, что видит клиент. Проверяем её, а не только набор строк."""
        quote, _ = set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        assert quote.charges_total == Decimal("50.00")

        quote, _ = set_quote_delivery_basis(world["quote"].id, world["ddp"].id, world["seller"])
        assert quote.charges_total == Decimal("30.00"), "итог сложил старый фрахт с новой страховкой"

    def test_manual_rows_survive_the_switch(self, world):
        """Ручную строку продавца стирать нельзя — удаляются только нетронутые авто-строки."""
        manual_type = ChargeType.objects.get_or_create(code="PACKING", defaults={"name": "Упаковка", "sort_order": 30})[
            0
        ]
        set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        QuoteCharge.objects.create(
            quote=world["quote"], charge_type=manual_type, amount=Decimal("7.00"), from_template=False
        )

        quote, _ = set_quote_delivery_basis(world["quote"].id, world["ddp"].id, world["seller"])
        assert _charge_codes(quote) == {"INSURANCE", "PACKING"}

    def test_same_basis_reapply_is_idempotent(self, world):
        """Повторный выбор ТОГО ЖЕ базиса ничего не удаляет и не дублирует."""
        set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        quote, _ = set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        assert quote.charges.filter(charge_type__code="FREIGHT").count() == 1

    def test_clearing_basis_drops_template_rows(self, world):
        """Снятие базиса (basis_id=None) — тоже смена: авто-строки уходят вместе с ним."""
        set_quote_delivery_basis(world["quote"].id, world["exw"].id, world["seller"])
        quote, error = set_quote_delivery_basis(world["quote"].id, None, world["seller"])
        assert error is None
        assert quote.delivery_basis_id is None
        assert _charge_codes(quote) == set()
        assert quote.charges_total == Decimal("0")


# ── Порядок каскада: в каскадной модели порядок меняет сумму ──────────────────


@pytest.mark.django_db
class TestReorderQuoteCharges:
    def _two_charges(self, world):
        first = QuoteCharge.objects.create(
            quote=world["quote"], charge_type=world["freight"], amount=Decimal("10.00"), sort_order=0
        )
        second = QuoteCharge.objects.create(
            quote=world["quote"], charge_type=world["insurance"], amount=Decimal("20.00"), sort_order=1
        )
        return first, second

    def test_buyer_cannot_reorder(self, world):
        quote, error = reorder_quote_charges(world["quote"].id, [], world["buyer"])
        assert quote is None
        assert error == "ONLY_SELLER_CAN_BUILD_QUOTE"

    def test_missing_quote_is_reported_not_crashed(self, world):
        quote, error = reorder_quote_charges(10**7, [], world["seller"])
        assert quote is None
        assert error == "QUOTE_NOT_FOUND"

    def test_frozen_quote_is_locked(self, world):
        from django.utils import timezone

        world["quote"].frozen_at = timezone.now()
        world["quote"].save(update_fields=["frozen_at"])
        quote, error = reorder_quote_charges(world["quote"].id, [], world["seller"])
        assert quote is None
        assert error == "QUOTE_FROZEN"

    def test_sort_order_follows_the_given_sequence(self, world):
        first, second = self._two_charges(world)
        quote, error = reorder_quote_charges(world["quote"].id, [second.id, first.id], world["seller"])
        assert error is None
        first.refresh_from_db()
        second.refresh_from_db()
        assert (second.sort_order, first.sort_order) == (0, 1)

    def test_unknown_id_is_ignored_not_fatal(self, world):
        """Устаревший id из клиента (строку удалили в другой вкладке) не должен ронять запрос."""
        first, second = self._two_charges(world)
        quote, error = reorder_quote_charges(world["quote"].id, [second.id, 10**7, first.id], world["seller"])
        assert error is None
        first.refresh_from_db()
        second.refresh_from_db()
        assert second.sort_order == 0
        assert first.sort_order == 2  # индекс в переданном списке, пропущенный id своё место занимает

    def test_charge_of_another_quote_is_not_touched(self, world):
        """Изоляция: id чужого КП в списке не должен переставлять чужую строку."""
        other_quote = Quote.objects.create(
            deal=world["quote"].deal,
            version=2,
            status=QuoteStatus.objects.get(code="DRAFT"),
            prepared_by=world["seller"],
            vat_rate=Decimal("12.00"),
        )
        foreign = QuoteCharge.objects.create(
            quote=other_quote, charge_type=world["freight"], amount=Decimal("5.00"), sort_order=9
        )
        own, _ = self._two_charges(world)

        quote, error = reorder_quote_charges(world["quote"].id, [foreign.id, own.id], world["seller"])
        assert error is None
        foreign.refresh_from_db()
        assert foreign.sort_order == 9, "переставлена строка чужого КП"


@pytest.mark.django_db
def test_templates_fall_back_to_quote_preparer_when_no_actor(world):
    """Вызов без актора (авто-генерация черновика КП) берёт шаблоны по автору КП.

    Ветка определяет, ЧЬИ шаблоны применятся. Ошибка здесь наложила бы на КП чужой
    профиль расходов — то есть чужие суммы.
    """
    from crm.services.charges import apply_charge_template_to_quote

    quote = world["quote"]
    quote.delivery_basis = world["exw"]
    quote.save(update_fields=["delivery_basis"])

    created = apply_charge_template_to_quote(quote, actor=None)
    assert created == 1
    assert _charge_codes(quote) == {"FREIGHT"}
