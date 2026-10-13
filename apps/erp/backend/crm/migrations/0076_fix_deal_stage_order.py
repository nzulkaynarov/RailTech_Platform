"""Починка порядка этапов воронки (ресерч владельца 2026-07-28 «воронка не работает»).

Симптом: «Заявка открыта» (RFQ_OPEN) — второй этап воронки — показывалась ПОСЛЕДНЕЙ в
дропдауне этапов, Канбане и воронке дашборда, после закрытых сделок.

Root cause: ранние сиды создали DealStage с sort_order 0–7 БЕЗ RFQ_OPEN; когда RFQ_OPEN
добавили (multi-seller routing), он получил хвостовой 25, а сид-миграция 0002 делает
get_or_create — существующие строки она НЕ чинит. Порядок в БД разъехался с каноном.

Фикс: принудительно выставить sort_order по DEAL_STAGE_CANONICAL_ORDER (crm/constants —
единый источник, его же читает core_seed и guard-тест). Трогаем ТОЛЬКО sort_order:
названия этапов — мастер-данные владельца, их не перезаписываем. Reverse — no-op
(возврат к сломанному порядку не нужен никогда).
"""

from django.db import migrations


def _fix_order(apps, schema_editor):
    from crm.constants import DEAL_STAGE_CANONICAL_ORDER

    deal_stage = apps.get_model("crm", "DealStage")
    for code, sort_order in DEAL_STAGE_CANONICAL_ORDER.items():
        deal_stage.objects.filter(code=code).update(sort_order=sort_order)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0075_dedupe_sample_template_titles"),
    ]

    operations = [
        migrations.RunPython(_fix_order, migrations.RunPython.noop),
    ]
