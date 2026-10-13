"""Дозаполнить `Fulfillment.contract` у существующих записей.

Без привязки к владельцу отгрузка попадает в фолбэк видимости продавца и становится видна
проигравшему со-роутед продавцу (см. `crm/services/fulfillment.ensure_fulfillment`). Код теперь
привязывает новые отгрузки, но исторические остались бы с NULL — то есть утечка на проде
сохранилась бы. Эта миграция закрывает уже созданные.

Берётся ПОДПИСАННЫЙ договор сделки (самый свежий), ровно как это делает
`auto_invoice_on_closed_won`. Сделки без подписанного договора остаются с NULL — там владельца
и нет, фолбэк для них законен.

Обратная операция — no-op: снимать привязку смысла нет, а откат не должен возвращать утечку.
"""

from django.db import migrations


def backfill_contract(apps, schema_editor):
    Fulfillment = apps.get_model("crm", "Fulfillment")
    Contract = apps.get_model("crm", "Contract")

    updated = 0
    for fulfillment in Fulfillment.objects.filter(contract__isnull=True).iterator():
        contract = (
            Contract.objects.filter(deal_id=fulfillment.deal_id, status__code="SIGNED")
            .order_by("-created_at")
            .first()
        )
        if contract is None:
            continue
        fulfillment.contract_id = contract.id
        fulfillment.save(update_fields=["contract"])
        updated += 1
    if updated:
        print(f"  Fulfillment: привязано к договору {updated} записей")


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0077_retire_kyc_pending_stage"),
    ]

    operations = [
        migrations.RunPython(backfill_contract, migrations.RunPython.noop),
    ]
