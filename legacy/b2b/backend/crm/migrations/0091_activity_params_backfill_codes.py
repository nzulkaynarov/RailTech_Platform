"""Старым строкам журнала дописываются КОДЫ в `event_params` (продолжение #523/#524).

Витрина подбирает подпись по коду, но у строк, записанных ДО этой правки, кода нет — и они
навсегда остались бы на языке того, кто действовал: в английской ленте «Deal #16: Черновик →
Открытый RFQ». Прецедент решения — миграция `0086_activity_log_one_word` (решение владельца
31-07, вариант «а»): отображательный текст переписывается данными, `event_code` неприкосновенен.

Коды НЕ угадываются:

* смена стадии и KYC — берутся из аудиторского снимка `before_data`/`after_data`, который
  пишет `log_admin_action` рядом с событием;
* роль шага согласования и роль компании — обратное отображение ЗАКРЫТОГО набора подписей
  (`StepParticipation.choices`, справочник `CompanyType`). Незнакомая подпись остаётся как есть.

Существующие ключи не перезаписываются, поэтому прогон идемпотентен. Обратная операция —
no-op: дописанный код ничему не мешает, а удалять его значило бы вернуть дефект.
"""

from django.db import migrations

#: Подписи ролей шага согласования → код. Набор закрыт (`crm.models.approvals.StepParticipation`).
PARTICIPATION_BY_LABEL = {
    "Руководитель": "HEAD",
    "Согласовант": "APPROVER",
    "Для информации": "INFORMED",
}

STAGE_EVENTS = ("deal.stage_changed", "deal.stage_changed_force")
KYC_EVENTS = ("company.kyc_verified", "company.kyc_downgraded")


def _fill(params: dict, key: str, value) -> bool:
    """Дописать ключ, если его ещё нет и значение непустое. True — если что-то изменилось."""
    if not value or params.get(key):
        return False
    params[key] = value
    return True


def backfill(apps, schema_editor):
    ActivityLog = apps.get_model("crm", "ActivityLog")
    CompanyType = apps.get_model("accounts", "CompanyType")

    role_code_by_name = {name: code for code, name in CompanyType.objects.values_list("code", "name")}

    updated = []
    rows = ActivityLog.objects.filter(
        event_code__in=[*STAGE_EVENTS, *KYC_EVENTS, "quote.approval_step_approved", "company.role_application_approved"]
    )
    for row in rows.iterator(chunk_size=500):
        params = dict(row.event_params or {})
        before = row.before_data or {}
        after = row.after_data or {}
        changed = False

        if row.event_code in STAGE_EVENTS:
            changed |= _fill(params, "from_stage_code", before.get("stage_code"))
            changed |= _fill(params, "to_stage_code", after.get("stage_code"))
        elif row.event_code in KYC_EVENTS:
            changed |= _fill(params, "from_status_code", before.get("verification_status"))
            changed |= _fill(params, "to_status_code", after.get("verification_status"))
        elif row.event_code == "quote.approval_step_approved":
            changed |= _fill(params, "participation_code", PARTICIPATION_BY_LABEL.get(params.get("participation")))
        elif row.event_code == "company.role_application_approved":
            changed |= _fill(params, "role_code", role_code_by_name.get(params.get("role_name")))

        if changed:
            row.event_params = params
            updated.append(row)
        if len(updated) >= 500:
            ActivityLog.objects.bulk_update(updated, ["event_params"])
            updated = []
    if updated:
        ActivityLog.objects.bulk_update(updated, ["event_params"])


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0090_receipt_delivery_note_samples"),
        # Справочник типов компании читается для обратного отображения имени роли в код.
        ("accounts", "0043_document_wording_fields"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
