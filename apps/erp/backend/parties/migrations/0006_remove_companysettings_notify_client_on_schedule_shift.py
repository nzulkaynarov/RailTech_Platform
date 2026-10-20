from django.db import migrations


class Migration(migrations.Migration):
    """FIX-4xb: флаг никто не читал; политика уведомлений о сдвигах появится в M4-ERP-03 (ADR-0008)."""

    dependencies = [
        ("parties", "0005_company_consent"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companysettings",
            name="notify_client_on_schedule_shift",
        ),
    ]
