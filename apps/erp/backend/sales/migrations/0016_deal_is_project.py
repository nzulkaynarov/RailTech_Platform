"""Стадия номера сделки полем (задача «Н», решение владельца 2026-11-13): заявка или проект — не по префиксу номера.

Триггеры pghistory пересоздаются под новое поле; существующие проекты (`ПР-…`) отмечаются заполнением."""

import pgtrigger.compiler
import pgtrigger.migrations
from django.db import migrations, models


def backfill(apps, schema_editor):
    Deal = apps.get_model("sales", "Deal")
    Deal.objects.filter(number__startswith="ПР-").update(is_project=True)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0015_official_signing"),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name="deal",
            name="deal_snapshot_insert_or_update",
        ),
        pgtrigger.migrations.RemoveTrigger(
            model_name="deal",
            name="deal_before_update_update",
        ),
        migrations.AddField(
            model_name="deal",
            name="is_project",
            field=models.BooleanField(default=False, editable=False, verbose_name="Проект (КП принято)"),
        ),
        migrations.AddField(
            model_name="dealevent",
            name="is_project",
            field=models.BooleanField(default=False, editable=False, verbose_name="Проект (КП принято)"),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="deal",
            trigger=pgtrigger.compiler.Trigger(
                name="deal_snapshot_insert_or_update",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    func='INSERT INTO "sales_dealevent" ("assigned_at", "assigned_to_id", "client_id", "company_id", "contact_id", "created_at", "crm_request_id", "id", "is_project", "manager_id", "notes", "number", "number_seq", "number_year", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "process", "stage_id", "title", "updated_at", "urgency") VALUES (NEW."assigned_at", NEW."assigned_to_id", NEW."client_id", NEW."company_id", NEW."contact_id", NEW."created_at", NEW."crm_request_id", NEW."id", NEW."is_project", NEW."manager_id", NEW."notes", NEW."number", NEW."number_seq", NEW."number_year", _pgh_attach_context(), NOW(), \'deal.snapshot\', NEW."id", NEW."process", NEW."stage_id", NEW."title", NEW."updated_at", NEW."urgency"); RETURN NULL;',
                    hash="5d43fedb7a9f49cd658877fec1101d431a3105e0",
                    operation="INSERT OR UPDATE",
                    pgid="pgtrigger_deal_snapshot_insert_or_update_6beb5",
                    table="sales_deal",
                    when="AFTER",
                ),
            ),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name="deal",
            trigger=pgtrigger.compiler.Trigger(
                name="deal_before_update_update",
                sql=pgtrigger.compiler.UpsertTriggerSql(
                    condition="WHEN (OLD.* IS DISTINCT FROM NEW.*)",
                    func='INSERT INTO "sales_dealevent" ("assigned_at", "assigned_to_id", "client_id", "company_id", "contact_id", "created_at", "crm_request_id", "id", "is_project", "manager_id", "notes", "number", "number_seq", "number_year", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "process", "stage_id", "title", "updated_at", "urgency") VALUES (OLD."assigned_at", OLD."assigned_to_id", OLD."client_id", OLD."company_id", OLD."contact_id", OLD."created_at", OLD."crm_request_id", OLD."id", OLD."is_project", OLD."manager_id", OLD."notes", OLD."number", OLD."number_seq", OLD."number_year", _pgh_attach_context(), NOW(), \'deal.before_update\', OLD."id", OLD."process", OLD."stage_id", OLD."title", OLD."updated_at", OLD."urgency"); RETURN NULL;',
                    hash="e322749a860c568cec147c9fbcc15cb92c02f3bf",
                    operation="UPDATE",
                    pgid="pgtrigger_deal_before_update_update_022ec",
                    table="sales_deal",
                    when="AFTER",
                ),
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
