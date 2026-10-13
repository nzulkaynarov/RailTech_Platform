from django.db import migrations


def backfill_draft_status(apps, schema_editor):
    """КП created before the perform_create fix had status=NULL, which left the
    approval chain (документооборот) with no actions — the seller could not submit
    the КП for review. Any quote that never advanced (NULL status) is logically a
    DRAFT, so backfill it. Quotes already SENT/APPROVED/etc. are untouched."""
    Quote = apps.get_model("crm", "Quote")
    QuoteStatus = apps.get_model("crm", "QuoteStatus")
    try:
        draft = QuoteStatus.objects.get(code="DRAFT")
    except QuoteStatus.DoesNotExist:
        return
    Quote.objects.filter(status__isnull=True).update(status=draft)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0013_alter_deal_created_at"),
    ]

    operations = [
        migrations.RunPython(backfill_draft_status, noop),
    ]
