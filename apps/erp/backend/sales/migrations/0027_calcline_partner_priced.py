from django.db import migrations, models


def backfill(apps, schema_editor):
    """Строки с выбранной ценой внешнего партнёра считались взятыми из неё (как до флага)."""
    from core.tenant import own_company_id

    CalcLine = apps.get_model("sales", "CalcLine")
    lines = CalcLine.objects.filter(item__offer__isnull=False)
    try:
        own = own_company_id()
    except Exception:  # noqa: BLE001 - нет владельца (пустая база): переносить нечего
        own = None
    if own:
        lines = lines.exclude(item__offer__supplier_id=own)
    lines.update(partner_priced=True)


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
