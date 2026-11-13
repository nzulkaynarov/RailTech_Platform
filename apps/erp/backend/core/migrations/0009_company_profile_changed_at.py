"""Время применённого снимка профиля компании из CRM (задача «Н3a2»): старый снимок не затирает новый."""

import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_country_names"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="systemsetting",
            name="system_setting_snapshot_update",
        ),
        migrations.AddField(
            model_name="systemsetting",
            name="company_profile_changed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="systemsettingevent",
            name="company_profile_changed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="systemsetting",
            trigger=pgtrigger.compiler.Trigger(
                name="system_setting_snapshot_update",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition="WHEN (OLD.* IS DISTINCT FROM NEW.*)",
                    func='INSERT INTO "core_systemsettingevent" ("company_profile_changed_at", "domain", "id", "is_two_factor_required", "logo_url", "maintenance_mode", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "platform_name", "standard_margin", "support_email", "updated_at", "vat_rate") VALUES (NEW."company_profile_changed_at", NEW."domain", NEW."id", NEW."is_two_factor_required", NEW."logo_url", NEW."maintenance_mode", _pgh_attach_context(), NOW(), \'system_setting.snapshot\', NEW."id", NEW."platform_name", NEW."standard_margin", NEW."support_email", NEW."updated_at", NEW."vat_rate"); RETURN NULL;',
                    hash="9ddffc02628cc8f17c07f76147eead65def05237",
                    operation="UPDATE",
                    pgid="pgtrigger_system_setting_snapshot_update_84c50",
                    table="core_systemsetting",
                    when="AFTER",
                ),
            ),
        ),
    ]
