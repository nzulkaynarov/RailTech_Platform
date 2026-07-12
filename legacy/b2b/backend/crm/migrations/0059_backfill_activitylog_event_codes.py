"""Backfill event_code on historical ActivityLog rows (spec-timeline-i18n 2026-07-12).

Two classes of legacy rows predate the structured-event pipeline (crm/0058):

1. RAW-KEY rows — crm/services/approvals.py used to write the machine key itself into
   `action` ("quote.approval_approve", …), which rendered LITERALLY on the buyer-facing
   timeline. Those get the new event_code AND a human RU `action` so every fallback
   surface (Unfold, old clients) stops showing keys.

2. DETERMINISTIC-TITLE rows — producers always wrote fixed RU strings ("Стадия изменена",
   "КП отправлено клиенту", …). Exact matches get their event_code so the timeline TITLE
   localizes by viewer locale. `event_params` stays {} (the values are baked into the RU
   `detail` prose and can't be recovered) — the frontend renders the translated title and
   falls back to the raw RU detail (lib/activityText.ts guards against interpolating a
   {{placeholder}} template with no params).

Reverse is a no-op: event_code='' rows simply render from `action` again.
"""

from django.db import migrations

# Old raw machine keys → (new event_code, human RU action to display on fallback surfaces).
RAW_KEY_MAP = {
    "quote.submit_for_review": ("quote.submitted_for_review", "КП отправлен на согласование"),
    "quote.approval_approve": ("quote.approval_step_approved", "Шаг согласования пройден"),
    "quote.approval_complete": ("quote.approval_complete", "Согласование КП завершено"),
    "quote.approval_reject": ("quote.approval_step_rejected", "Согласование отклонено"),
    "quote.approval_recall": ("quote.approval_recalled", "КП отозван из согласования"),
}

# Deterministic RU titles producers have always written verbatim → event_code.
# Titles with dynamic parts (f-strings) are intentionally absent — they stay legacy.
TITLE_MAP = {
    "[MANUAL_MODE] Подписан акт": "act.signed",
    "KYC: понижение уровня": "company.kyc_downgraded",
    "KYC: подтверждение": "company.kyc_verified",
    "Слияние дубля компании": "company.merged",
    "Заявка на роль одобрена": "company.role_application_approved",
    "Авто-переход в CLOSED_WON не выполнен": "contract.auto_close_failed",
    "[FORCE_ADMIN] Контракт отменён платформенным админом": "contract.cancelled_force",
    "Создан контракт": "contract.created",
    "[MANUAL_MODE] Подписан контракт (сторона клиента)": "contract.signed_client",
    "[MANUAL_MODE] Подписан контракт (сторона RailTech)": "contract.signed_manager",
    "Заявка назначена": "deal.assigned",
    "Сообщение в чате сделки": "deal.chat_message",
    "Заявка взята в работу": "deal.claimed",
    "Сделка создана": "deal.created",
    "Добавлена позиция заявки": "deal.item_added",
    "Удалена позиция заявки": "deal.item_removed",
    "Добавлены позиции заявки (корзина)": "deal.items_added_bulk",
    "Заявка возвращена в очередь": "deal.released",
    "Заявка адресована продавцам (RFQ routing)": "deal.routed",
    "Стадия изменена": "deal.stage_changed",
    "Force: стадия изменена": "deal.stage_changed_force",
    "Заявка отправлена поставщику (RFQ)": "deal.submitted",
    "Инвойс выставлен": "invoice.issued",
    "Lead конвертирован в сделку": "lead.converted",
    "Новый лид с сайта": "lead.received",
    "Зафиксирован платёж": "payment.recorded",
    "[MANUAL_MODE] Зафиксирован платёж": "payment.recorded",
    "КП принято клиентом": "quote.accepted",
    "Согласование КП завершено": "quote.approval_complete",
    "КП отозван из согласования": "quote.approval_recalled",
    "Шаг согласования пройден": "quote.approval_step_approved",
    "Согласование отклонено": "quote.approval_step_rejected",
    "[FORCE_ADMIN] КП одобрено платформенным админом": "quote.approved_force",
    "КП просрочено": "quote.expired",
    "Переназначен продукт в позиции КП": "quote.item_rematched",
    "КП отклонено клиентом": "quote.rejected",
    "КП отправлено клиенту": "quote.sent",
    "КП отправлен на согласование": "quote.submitted_for_review",
    "Оплата подписки": "subscription.paid",
    "[MANUAL_MODE] Оплата подписки": "subscription.paid",
}


def backfill(apps, schema_editor):
    activity_log = apps.get_model("crm", "ActivityLog")
    for raw_key, (event_code, human_action) in RAW_KEY_MAP.items():
        activity_log.objects.filter(event_code="", action=raw_key).update(
            event_code=event_code, action=human_action
        )
    for title, event_code in TITLE_MAP.items():
        activity_log.objects.filter(event_code="", action=title).update(event_code=event_code)


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0058_activitylog_event_code_activitylog_event_params"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
