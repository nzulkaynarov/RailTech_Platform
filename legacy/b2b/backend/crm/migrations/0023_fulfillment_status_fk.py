"""F5.4 — convert Fulfillment.status CharField → FK(FulfillmentStatus).

Hand-written (the autodetector would Remove+Add and lose data): rename the old
CharField aside, add the FK, copy each row's code → the matching lookup row, then
drop the old column. Fulfillment is NOT pghistory-tracked, so no event table to
migrate (unlike Contract/Invoice/Act, handled separately).
"""

import django.db.models.deletion
from django.db import migrations, models


def copy_forward(apps, schema_editor):
    Fulfillment = apps.get_model("crm", "Fulfillment")
    FulfillmentStatus = apps.get_model("crm", "FulfillmentStatus")
    by_code = {s.code: s for s in FulfillmentStatus.objects.all()}
    for fulfillment in Fulfillment.objects.all():
        fulfillment.status = by_code.get(fulfillment.status_old)
        fulfillment.save(update_fields=["status"])


def copy_backward(apps, schema_editor):
    Fulfillment = apps.get_model("crm", "Fulfillment")
    for fulfillment in Fulfillment.objects.all():
        fulfillment.status_old = fulfillment.status.code if fulfillment.status_id else "PENDING"
        fulfillment.save(update_fields=["status_old"])


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0022_actstatus_contractstatus_fulfillmentstatus_and_more"),
    ]

    operations = [
        migrations.RenameField("fulfillment", "status", "status_old"),
        migrations.AddField(
            model_name="fulfillment",
            name="status",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fulfillments",
                to="crm.fulfillmentstatus",
                verbose_name="Статус",
            ),
        ),
        migrations.RunPython(copy_forward, copy_backward),
        migrations.RemoveField(model_name="fulfillment", name="status_old"),
    ]
