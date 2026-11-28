from django.db import migrations, models, transaction


def _own_company_id():
    """Id компании-владельца или None; сбой поиска (в т.ч. SQL-ошибка) не должен ронять транзакцию миграции."""
    from core.tenant import own_company_id

    try:
        with transaction.atomic():  # savepoint: упавший запрос откатывается отдельно от миграции
            return own_company_id()
    except Exception:  # noqa: BLE001 - владелец не определён: «внешний» поставщик неизвестен
        return None


def backfill(apps, schema_editor):
    """Флаг ставится только там, где закупка строки всё ещё равна цене и валюте внешнего предложения.

    Строка с рукой правленной закупкой (до РАСЧ-1 правка не снимала `offer`) остаётся False: ложное «Партнёр · до …»
    хуже отсутствующего. Владелец не определён — не ставим ничего (сомнение = False)."""
    CalcLine = apps.get_model("sales", "CalcLine")
    own = _own_company_id()
    if not own:
        return
    CalcLine.objects.filter(
        item__offer__isnull=False,
        item__frozen_base_price=models.F("item__offer__base_price"),
        item__frozen_currency_id=models.F("item__offer__currency_id"),
    ).exclude(item__offer__supplier_id=own).update(partner_priced=True)


class Migration(migrations.Migration):
    dependencies = [("sales", "0026_dp1_contract_remarks")]

    operations = [
        migrations.AddField(
            model_name="calcline",
            name="partner_priced",
            field=models.BooleanField(
                default=False,
                help_text="РАСЧ-1: закупка взята из цены партнёра; ручная правка снимает флаг, поставщик строки (offer) остаётся",
                verbose_name="Закупка из цены партнёра",
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
