"""DT1 — позиционное переопределение маржи (семантика Salesforce CPQ / Odoo).

Контракт, который здесь закрепляется:

  * ``QuoteItem.margin_percent IS NULL``  → переопределения нет, строка наследует
    ``Quote.margin_percent`` (дефолт для любой новой строки);
  * ``QuoteItem.margin_percent`` = число → явное переопределение, ПОБЕЖДАЕТ маржу КП,
    причём явный ``0`` — осмысленное значение «продать по себестоимости», а не «не задано»;
  * ``QuoteItemHistory.margin_percent`` пишет ЭФФЕКТИВНУЮ (реально применённую) маржу;
  * **и главное** — миграция 0063 не меняет цену НИ ОДНОГО существующего КП
    (см. ``TestZeroPricingChangeOnMigration``).

Последний пункт — причина, по которой колонка вообще сделана nullable: до DT1 движок
позиционное значение игнорировал, поэтому у всех исторических строк там лежит НИКОГДА не
применявшееся число (обычно 0). Дать ему «победить» задним числом = молча обнулить маржу
всех ранее выставленных КП.
"""

from decimal import Decimal

import pytest
from django.apps import apps as global_apps

from crm.models import Deal, Quote, QuoteItem, QuoteItemHistory, QuoteStatus
from crm.services import QuoteCalculationService
from crm.services.quotes.pricing import resolve_effective_margin

pytestmark = pytest.mark.django_db


def _deal():
    from accounts.models import Company

    company = Company.objects.create(name="DT1 Trading LLC", inn="998877665")
    return Deal.objects.create(company=company, title="DT1 per-line margin deal")


def _quote(deal, margin):
    """Черновой КП с НУЛЕВЫМ НДС и без статей расхода — чтобы subtotal был чистой суммой
    строк и тест мерил именно маржу, а не каскад начислений."""
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.filter(code="DRAFT").first(),
        margin_percent=Decimal(margin),
        vat_rate=Decimal("0"),
    )


def _line(quote, base, margin=..., quantity=1):
    """Строка КП. ``margin`` не передан → колонка остаётся NULL («наследовать»);
    передан (в т.ч. 0) → явное позиционное переопределение."""
    item = QuoteItem(
        quote=quote,
        imported_raw_name=f"DT1 line {base}",
        quantity=quantity,
        frozen_base_price=Decimal(base),
    )
    if margin is not ...:
        item.margin_percent = None if margin is None else Decimal(margin)
    item.save(skip_recalculate=True)
    return item


class TestInheritWhenNull:
    def test_null_line_inherits_quote_margin(self):
        # КП-маржа 20%, у строки переопределения нет → 100 × 1.20 = 120.
        quote = _quote(_deal(), "20")
        item = _line(quote, "100")
        assert item.margin_percent is None, "новая строка обязана быть NULL, а не 0"

        QuoteCalculationService.recalculate_quote(quote.id)

        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("120.00")

    def test_changing_quote_margin_moves_every_inheriting_line(self):
        """Смысл наследования: правка маржи КП пересчитывает все НЕ переопределённые строки."""
        quote = _quote(_deal(), "10")
        item = _line(quote, "200")
        QuoteCalculationService.recalculate_quote(quote.id)
        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("220.00")

        quote.margin_percent = Decimal("50")
        quote.save(update_fields=["margin_percent"])
        QuoteCalculationService.recalculate_quote(quote.id)

        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("300.00")  # 200 × 1.50


class TestExplicitOverrideWins:
    def test_override_beats_quote_margin(self):
        # КП 20%, строка 50% → побеждает строка: 100 × 1.50 = 150.
        quote = _quote(_deal(), "20")
        item = _line(quote, "100", margin="50")

        QuoteCalculationService.recalculate_quote(quote.id)

        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("150.00")

    def test_explicit_zero_means_zero_margin_not_inherit(self):
        """КЛЮЧЕВОЕ различие, ради которого колонка стала nullable: явный 0 ≠ «не задано».

        КП-маржа 30%, но менеджер осознанно продаёт позицию по себестоимости.
        """
        quote = _quote(_deal(), "30")
        item = _line(quote, "100", margin="0")

        QuoteCalculationService.recalculate_quote(quote.id)

        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("100.00")  # НЕ 130.00

    def test_override_and_inherit_coexist_on_one_quote(self):
        quote = _quote(_deal(), "20")
        inheriting = _line(quote, "100")  # → 120.00
        overridden = _line(quote, "100", margin="0")  # → 100.00

        QuoteCalculationService.recalculate_quote(quote.id)

        inheriting.refresh_from_db()
        overridden.refresh_from_db()
        assert inheriting.final_price_excl_vat == Decimal("120.00")
        assert overridden.final_price_excl_vat == Decimal("100.00")
        quote.refresh_from_db()
        assert quote.subtotal_excl_vat == Decimal("220.00")

    def test_discount_still_applies_after_the_override(self):
        # Переопределение меняет только наценку; скидка позиции по-прежнему идёт следом.
        quote = _quote(_deal(), "0")
        item = _line(quote, "100", margin="20")
        item.discount_percent = Decimal("10")
        item.save(skip_recalculate=True)

        QuoteCalculationService.recalculate_quote(quote.id)

        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("108.00")  # 100 × 1.20 × 0.90


class TestItemSaveWithNullMargin:
    def test_direct_save_does_not_crash_and_inherits(self):
        """``QuoteItem.save`` зовёт движок БЕЗ КП-маржи. С nullable-колонкой наивная
        реализация упала бы на ``None / Decimal('100')`` — резолвер обязан достать
        маржу с связанного КП."""
        quote = _quote(_deal(), "25")
        item = QuoteItem(
            quote=quote,
            imported_raw_name="Saved directly",
            quantity=1,
            frozen_base_price=Decimal("400"),
        )
        item.save()  # полный путь, с пересчётом КП

        item.refresh_from_db()
        assert item.final_price_excl_vat == Decimal("500.00")  # 400 × 1.25

    def test_in_memory_item_without_quote_defaults_to_zero_margin(self):
        """Чистый in-memory путь (юнит-тесты движка): наследовать не от кого → 0%."""
        orphan = QuoteItem(frozen_base_price=Decimal("100"), quantity=1)
        assert orphan.margin_percent is None
        QuoteCalculationService.calculate_item_prices(orphan, commit=False)
        assert orphan.final_price_excl_vat == Decimal("100.00")


class TestAuditHistoryRecordsEffectiveMargin:
    def test_history_logs_applied_margin_for_inheriting_line(self):
        """Раньше сюда писался сырой item.margin_percent, который расчёт игнорировал —
        аудит-след противоречил цене. Теперь пишем то, что реально применено."""
        quote = _quote(_deal(), "20")
        item = _line(quote, "100")

        QuoteCalculationService.recalculate_quote(quote.id)

        record = QuoteItemHistory.objects.filter(quote_item=item).latest("id")
        assert record.margin_percent == Decimal("20.00"), "унаследованная маржа КП"
        assert record.final_price_excl_vat == Decimal("120.00")

    def test_history_logs_override_for_overridden_line(self):
        quote = _quote(_deal(), "20")
        item = _line(quote, "100", margin="50")

        QuoteCalculationService.recalculate_quote(quote.id)

        record = QuoteItemHistory.objects.filter(quote_item=item).latest("id")
        assert record.margin_percent == Decimal("50.00")

    def test_history_margin_is_consistent_with_the_price_it_records(self):
        """Инвариант аудита: цену из записи можно воспроизвести её же маржой."""
        quote = _quote(_deal(), "35")
        item = _line(quote, "250", margin="0")

        QuoteCalculationService.recalculate_quote(quote.id)

        record = QuoteItemHistory.objects.filter(quote_item=item).latest("id")
        expected = record.landed_cost * (Decimal("1") + record.margin_percent / Decimal("100"))
        assert record.final_price_excl_vat == expected.quantize(Decimal("0.01"))


class TestResolveEffectiveMargin:
    """Резолвер — единая точка истины; он же кормит и цену, и аудит."""

    def test_override_wins_over_passed_quote_margin(self):
        item = QuoteItem(margin_percent=Decimal("7"))
        assert resolve_effective_margin(item, Decimal("20")) == Decimal("7")

    def test_explicit_zero_wins_over_passed_quote_margin(self):
        item = QuoteItem(margin_percent=Decimal("0"))
        assert resolve_effective_margin(item, Decimal("20")) == Decimal("0")

    def test_null_falls_back_to_passed_quote_margin(self):
        item = QuoteItem(margin_percent=None)
        assert resolve_effective_margin(item, Decimal("20")) == Decimal("20")

    def test_null_without_quote_is_zero(self):
        assert resolve_effective_margin(QuoteItem(margin_percent=None), None) == Decimal("0")


class TestZeroPricingChangeOnMigration:
    """ГЛАВНАЯ гарантия DT1: применение миграции 0063 к СУЩЕСТВУЮЩИМ данным не меняет
    цену ни на копейку.

    Метод доказательства: воспроизводим строки ровно в том виде, в каком они лежат в БД до
    миграции (margin_percent NOT NULL — 0 и «мусорные» ненулевые значения, которые движок
    игнорировал), считаем ожидаемые итоги НЕЗАВИСИМОЙ формулой старого движка
    (`landed × (1 + МАРЖА_КП/100)` — позиционное значение не участвует), затем прогоняем
    саму data-функцию миграции и пересчитываем КП новым движком. Итоги обязаны совпасть.
    """

    @staticmethod
    def _migration_data_step():
        from core.legacy_migration_helpers import null_out_never_applied_margins

        return null_out_never_applied_margins

    def _legacy_quote_with_rows(self):
        """КП «как до миграции»: у каждой строки в колонке лежит НЕ-NULL значение, которое
        старый движок не применял. Пишем через .update(), т.к. модель уже даёт NULL-дефолт."""
        quote = _quote(_deal(), "20")
        rows = [
            (_line(quote, "100", quantity=10), Decimal("0")),  # типичная историческая строка
            (_line(quote, "50", quantity=4), Decimal("10")),  # «мусорное» ненулевое значение
            (_line(quote, "33.33", quantity=3), Decimal("500")),  # крайний случай
        ]
        for item, legacy_margin in rows:
            QuoteItem.objects.filter(pk=item.pk).update(margin_percent=legacy_margin)
        return quote, [item for item, _ in rows]

    @staticmethod
    def _legacy_price(item, quote):
        """Оракул СТАРОГО движка: маржа КП побеждает всегда, позиционная игнорируется."""
        mult = Decimal("1") + quote.margin_percent / Decimal("100")
        return (item.frozen_base_price * mult).quantize(Decimal("0.01"))

    def test_totals_are_identical_before_and_after_the_migration(self):
        """Сравниваем СТАРЫЙ движок на до-миграционных данных с НОВЫМ на после-миграционных.

        Именно эта пара и есть «ничего не изменилось для владельца КП». Сравнивать новый
        движок сам с собой до/после миграции БЕССМЫСЛЕННО: на до-миграционных данных
        (margin NOT NULL) он как раз и даёт ту самую катастрофу, которую миграция снимает.
        """
        quote, items = self._legacy_quote_with_rows()

        expected_subtotal = sum(
            (self._legacy_price(item, quote) * item.quantity for item in items),
            Decimal("0"),
        )
        # Цены, реально лежащие в БД до миграции, обязаны совпадать с оракулом —
        # подтверждает, что фикстура воспроизводит боевое до-миграционное состояние.
        for item in items:
            stored = QuoteItem.objects.get(pk=item.pk)
            assert stored.margin_percent is not None, "фикстура обязана быть до-миграционной"
            assert stored.final_price_excl_vat == self._legacy_price(item, quote)

        # ── применяем шаг данных миграции 0063 ───────────────────────────────
        self._migration_data_step()(global_apps, None)
        assert not QuoteItem.objects.filter(quote=quote, margin_percent__isnull=False).exists()

        QuoteCalculationService.recalculate_quote(quote.id)
        quote.refresh_from_db()

        assert quote.subtotal_excl_vat == expected_subtotal
        # НДС на этом КП 0 ⇒ полная сумма равна subtotal; проверяем и её, т.к. владельца
        # интересует именно итог документа.
        assert quote.total_incl_vat == expected_subtotal

    def test_no_line_price_changes(self):
        """Тот же инвариант на уровне КАЖДОЙ строки, а не только итога (чтобы взаимно
        компенсирующиеся сдвиги не спрятались в сумме)."""
        quote, items = self._legacy_quote_with_rows()
        before = {item.pk: QuoteItem.objects.get(pk=item.pk).final_price_excl_vat for item in items}

        self._migration_data_step()(global_apps, None)
        QuoteCalculationService.recalculate_quote(quote.id)

        after = {item.pk: QuoteItem.objects.get(pk=item.pk).final_price_excl_vat for item in items}
        assert after == before
        # И совпадает с независимым оракулом старого движка, а не просто «само с собой».
        assert after == {item.pk: self._legacy_price(item, quote) for item in items}

    def test_fixture_would_break_without_the_data_step(self):
        """Негативный контроль: без шага данных цена ПОЕХАЛА БЫ. Если этот тест когда-нибудь
        начнёт падать — значит миграция данных перестала быть нужной, и её удаление безопасно;
        пока он проходит, удалять RunPython НЕЛЬЗЯ."""
        quote, items = self._legacy_quote_with_rows()
        expected = {item.pk: self._legacy_price(item, quote) for item in items}

        # Пересчёт НОВЫМ движком БЕЗ миграции — позиционные «мусорные» значения оживают.
        QuoteCalculationService.recalculate_quote(quote.id)

        without_migration = {item.pk: QuoteItem.objects.get(pk=item.pk).final_price_excl_vat for item in items}
        assert without_migration != expected, "без data-миграции цены обязаны разъехаться"

    def test_migration_is_reversible_back_to_zero(self):
        from types import SimpleNamespace

        from core.legacy_migration_helpers import null_out_never_applied_margins, restore_zero_margins

        module = SimpleNamespace(
            null_out_never_applied_margins=null_out_never_applied_margins,
            restore_zero_margins=restore_zero_margins,
        )

        quote, items = self._legacy_quote_with_rows()
        module.null_out_never_applied_margins(global_apps, None)

        module.restore_zero_margins(global_apps, None)

        # Обратный шаг обязан снять ВСЕ NULL — иначе колонку не вернуть в NOT NULL.
        assert not QuoteItem.objects.filter(margin_percent__isnull=True).exists()
