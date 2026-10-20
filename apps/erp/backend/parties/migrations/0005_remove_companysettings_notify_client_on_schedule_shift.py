from django.db import migrations


class Migration(migrations.Migration):
    """FIX-4xb: флаг никто не читал; политика уведомлений о сдвигах появится в M4-ERP-03 (ADR-0008)."""

    dependencies = [
        ("parties", "0004_portal_contact_and_company_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="companysettings",
            name="notify_client_on_schedule_shift",
        ),
    ]
