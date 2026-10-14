"""История сделки говорит теми же словами, что продукт (D3 → миграция crm/0086).

Старые строки ActivityLog заморожены на момент записи и печатали «Инвойс выставлен» /
«Подписан контракт» рядом с интерфейсом, где документы зовутся «Счёт» и «Договор». Решение
владельца (хендофф 31-07 §3, вариант «а»): текст отображательный — переписывается данными,
`event_code`/`event_params` неприкосновенны.
"""

from types import SimpleNamespace

import pytest
from django.apps import apps

from core.legacy_migration_helpers import rewrite_activity_logs, rewrite_text

migration = SimpleNamespace(rewrite_text=rewrite_text, rewrite=rewrite_activity_logs)


def test_rewrite_covers_declensions_and_keeps_case():
    assert migration.rewrite_text("Инвойс выставлен") == "Счёт выставлен"
    assert migration.rewrite_text("По сделке выставлен инвойс к оплате") == "По сделке выставлен счёт к оплате"
    assert migration.rewrite_text("Подписан контракт (сторона клиента)") == "Подписан договор (сторона клиента)"
    assert migration.rewrite_text("Контракт CT-2026-0007 по сделке") == "Договор CT-2026-0007 по сделке"
    assert migration.rewrite_text("Отмена инвойса по контракту") == "Отмена счёта по договору"
    assert migration.rewrite_text("Сводка по инвойсам и контрактам") == "Сводка по счетам и договорам"


def test_rewrite_respects_word_boundaries():
    """«Контрактный», номера вида CT-… и латиница не трогаются — замена только целых слов."""
    assert migration.rewrite_text("контрактный отдел") == "контрактный отдел"
    assert migration.rewrite_text("Invoice INV-1 issued") == "Invoice INV-1 issued"
    assert migration.rewrite_text("") == ""


@pytest.mark.django_db
def test_migration_rewrites_action_and_detail_but_not_event_code():
    from crm.models import ActivityLog

    row = ActivityLog.objects.create(
        action="Инвойс выставлен",
        detail="Инвойс INV-2026-00001 по сделке #7 (без контракта)",
        event_code="invoice.issued",
        event_params={},
    )
    untouched = ActivityLog.objects.create(action="КП отправлено клиенту", event_code="quote.sent")

    migration.rewrite(apps, None)

    row.refresh_from_db()
    untouched.refresh_from_db()
    assert row.action == "Счёт выставлен"
    assert row.detail == "Счёт INV-2026-00001 по сделке #7 (без договора)"
    assert row.event_code == "invoice.issued", "машинный код события неприкосновенен"
    assert untouched.action == "КП отправлено клиенту"


@pytest.mark.django_db
def test_migration_is_idempotent():
    from crm.models import ActivityLog

    row = ActivityLog.objects.create(action="[MANUAL_MODE] Подписан контракт (сторона клиента)")
    migration.rewrite(apps, None)
    migration.rewrite(apps, None)
    row.refresh_from_db()
    assert row.action == "[MANUAL_MODE] Подписан договор (сторона клиента)"
