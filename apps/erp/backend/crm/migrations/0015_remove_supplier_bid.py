from django.db import migrations


class Migration(migrations.Migration):
    """Remove the SupplierBid / tender / open-RFQ feature.

    The supplier-bidding flow (SupplierBid + SupplierBidItem) is dropped from the
    product. Delete the child model first (SupplierBidItem → SupplierBid FK), then
    the parent.
    """

    dependencies = [
        ("crm", "0014_backfill_quote_draft_status"),
    ]

    operations = [
        migrations.DeleteModel(name="SupplierBidItem"),
        migrations.DeleteModel(name="SupplierBid"),
    ]
