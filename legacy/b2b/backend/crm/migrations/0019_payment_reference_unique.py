from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0018_remove_quoteitem_quote_item_snapshot_insert_or_update_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                fields=["invoice", "reference"],
                condition=models.Q(("reference", ""), _negated=True),
                name="uniq_payment_invoice_reference",
            ),
        ),
    ]
