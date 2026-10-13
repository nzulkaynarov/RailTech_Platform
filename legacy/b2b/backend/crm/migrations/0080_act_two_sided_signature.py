"""Акт становится двусторонним документом (G2).

Раньше у акта было одно поле `signed_at` и НИ ОДНОГО подписанта: кто закрыл документ, нигде
не сохранялось, а закрыть его в одиночку могла любая сторона сделки. Между тем акт —
двусторонний документ и в узбекской практике («подтверждён двумя сторонами», ГК РУз ст. 646),
и в российском ЭДО, где он физически состоит из двух титулов.

Бэкфилл историчных записей:
  * выпуск атрибутируется создателю акта — эти данные есть (`created_by` + `issued_at`);
  * приём проставляется по факту `signed_at`, но БЕЗ подписанта: кто именно принимал, система
    тогда не сохраняла, и придумывать его здесь нельзя.
"""

from datetime import datetime, time

import django.db.models.deletion
import pgtrigger.compiler
import pgtrigger.migrations
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def _as_datetime(issued_at, created_at):
    """`issued_at` — это ДАТА, а поле подписи хранит момент времени.

    Наивный datetime из даты Django принял бы с предупреждением и записал бы его как UTC,
    сместив момент. Поэтому дата разворачивается в начало суток в текущей таймзоне.
    """
    if issued_at is None:
        return created_at
    return timezone.make_aware(datetime.combine(issued_at, time.min))


def backfill_two_sided_signatures(apps, schema_editor):
    Act = apps.get_model("crm", "Act")

    # Выпуск: у любого не-черновика он состоялся — датой выставления, иначе датой создания.
    for act in Act.objects.exclude(status__code="DRAFT").filter(issuer_signed_at__isnull=True).iterator():
        act.issuer_signer_id = act.created_by_id
        act.issuer_signed_at = _as_datetime(act.issued_at, act.created_at)
        act.save(update_fields=["issuer_signer", "issuer_signed_at"])

    # Приём: только там, где акт реально подписан. Подписант остаётся NULL — честнее пустого
    # поля здесь только неправда.
    Act.objects.filter(signed_at__isnull=False, acceptor_signed_at__isnull=True).update(
        acceptor_signed_at=models.F("signed_at")
    )


def unbackfill(apps, schema_editor):
    """Обратный ход — поля просто очищаются; `signed_at` при этом не трогаем, он исходный."""
    Act = apps.get_model("crm", "Act")
    Act.objects.update(issuer_signer=None, issuer_signed_at=None, acceptor_signer=None, acceptor_signed_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0079_invoice_due_date_is_manual'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        pgtrigger.migrations.RemoveTrigger(
            model_name='act',
            name='act_snapshot_insert_or_update',
        ),
        pgtrigger.migrations.RemoveTrigger(
            model_name='act',
            name='act_before_update_update',
        ),
        migrations.AddField(
            model_name='act',
            name='acceptor_signed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Принят'),
        ),
        migrations.AddField(
            model_name='act',
            name='acceptor_signer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='acts_accepted', to=settings.AUTH_USER_MODEL, verbose_name='Принял (сторона заказчика)'),
        ),
        migrations.AddField(
            model_name='act',
            name='issuer_signed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Выпущен'),
        ),
        migrations.AddField(
            model_name='act',
            name='issuer_signer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='acts_issued', to=settings.AUTH_USER_MODEL, verbose_name='Выпустил (сторона исполнителя)'),
        ),
        migrations.AddField(
            model_name='act',
            name='rejection_reason',
            field=models.TextField(blank=True, help_text='Заполняется, когда заказчик отклоняет акт: основание попадает в аудит', verbose_name='Причина отклонения'),
        ),
        migrations.AddField(
            model_name='actevent',
            name='acceptor_signed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Принят'),
        ),
        migrations.AddField(
            model_name='actevent',
            name='acceptor_signer',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Принял (сторона заказчика)'),
        ),
        migrations.AddField(
            model_name='actevent',
            name='issuer_signed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Выпущен'),
        ),
        migrations.AddField(
            model_name='actevent',
            name='issuer_signer',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', related_query_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Выпустил (сторона исполнителя)'),
        ),
        migrations.AddField(
            model_name='actevent',
            name='rejection_reason',
            field=models.TextField(blank=True, help_text='Заполняется, когда заказчик отклоняет акт: основание попадает в аудит', verbose_name='Причина отклонения'),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='act',
            trigger=pgtrigger.compiler.Trigger(name='act_snapshot_insert_or_update', sql=pgtrigger.compiler.UpsertTriggerSql(func='INSERT INTO "crm_actevent" ("acceptor_signed_at", "acceptor_signer_id", "contract_id", "created_at", "created_by_id", "deal_id", "id", "invoice_id", "issued_at", "issuer_signed_at", "issuer_signer_id", "notes", "number", "pdf_file", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "rejection_reason", "signed_at", "signed_file", "status_id", "total_amount", "updated_at") VALUES (NEW."acceptor_signed_at", NEW."acceptor_signer_id", NEW."contract_id", NEW."created_at", NEW."created_by_id", NEW."deal_id", NEW."id", NEW."invoice_id", NEW."issued_at", NEW."issuer_signed_at", NEW."issuer_signer_id", NEW."notes", NEW."number", NEW."pdf_file", _pgh_attach_context(), NOW(), \'act.snapshot\', NEW."id", NEW."rejection_reason", NEW."signed_at", NEW."signed_file", NEW."status_id", NEW."total_amount", NEW."updated_at"); RETURN NULL;', hash='70e38826f7f998479e610671bf82954b81e7667c', operation='INSERT OR UPDATE', pgid='pgtrigger_act_snapshot_insert_or_update_3118d', table='crm_act', when='AFTER')),
        ),
        pgtrigger.migrations.AddTrigger(
            model_name='act',
            trigger=pgtrigger.compiler.Trigger(name='act_before_update_update', sql=pgtrigger.compiler.UpsertTriggerSql(condition='WHEN (OLD.* IS DISTINCT FROM NEW.*)', func='INSERT INTO "crm_actevent" ("acceptor_signed_at", "acceptor_signer_id", "contract_id", "created_at", "created_by_id", "deal_id", "id", "invoice_id", "issued_at", "issuer_signed_at", "issuer_signer_id", "notes", "number", "pdf_file", "pgh_context_id", "pgh_created_at", "pgh_label", "pgh_obj_id", "rejection_reason", "signed_at", "signed_file", "status_id", "total_amount", "updated_at") VALUES (OLD."acceptor_signed_at", OLD."acceptor_signer_id", OLD."contract_id", OLD."created_at", OLD."created_by_id", OLD."deal_id", OLD."id", OLD."invoice_id", OLD."issued_at", OLD."issuer_signed_at", OLD."issuer_signer_id", OLD."notes", OLD."number", OLD."pdf_file", _pgh_attach_context(), NOW(), \'act.before_update\', OLD."id", OLD."rejection_reason", OLD."signed_at", OLD."signed_file", OLD."status_id", OLD."total_amount", OLD."updated_at"); RETURN NULL;', hash='de82569fd8b0b8e5d260629a505858ea9f3365f8', operation='UPDATE', pgid='pgtrigger_act_before_update_update_d4964', table='crm_act', when='AFTER')),
        ),
        migrations.RunPython(backfill_two_sided_signatures, unbackfill),
    ]
