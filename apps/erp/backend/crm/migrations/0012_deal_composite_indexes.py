"""Composite indexes for the tenant-scoped Deal list and pipeline-by-stage queries."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0011_activitylog_after_data_activitylog_before_data_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="deal",
            index=models.Index(fields=["company", "-created_at"], name="deal_company_created_idx"),
        ),
        migrations.AddIndex(
            model_name="deal",
            index=models.Index(fields=["company", "stage"], name="deal_company_stage_idx"),
        ),
    ]
