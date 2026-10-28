"""ERP-09, данные: номера ЗВ-ГГГГ-NNN / ПР-ГГГГ-NNN сделкам, созданным до нумерации.

Год — дата создания по часовому поясу компании (`TIME_ZONE`), NNN — порядок создания в году (`created_at`, `id`); сделка
в стадии проекта (договор подписан или закрыта успешно) получает префикс ПР. Счётчик года (`DealNumberCounter`) встаёт на
последний выданный NNN — новые заявки продолжают без пропусков и повторов. Отдельно от схемы 0007: на PostgreSQL
изменение строк с триггерами pghistory и ALTER TABLE в одной транзакции дают «pending trigger events». Обратный ход —
номера стираются, счётчики удаляются.
"""

from collections import defaultdict
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import migrations

PROJECT_STAGES = ("CONTRACT_SIGNED", "CLOSED_WON")


def backfill(apps, schema_editor):
    Deal = apps.get_model("sales", "Deal")
    Counter = apps.get_model("sales", "DealNumberCounter")
    zone = ZoneInfo(settings.TIME_ZONE)
    last: dict[int, int] = defaultdict(int)
    for row in Counter.objects.all():
        last[row.year] = row.last_value
    pending = []
    for deal in Deal.objects.filter(number_seq__isnull=True).select_related("stage").order_by("created_at", "id"):
        year = deal.created_at.astimezone(zone).year
        last[year] += 1
        prefix = "ПР" if deal.stage_id and deal.stage.code in PROJECT_STAGES else "ЗВ"
        deal.number_year, deal.number_seq = year, last[year]
        deal.number = f"{prefix}-{year:04d}-{last[year]:03d}"
        pending.append(deal)
    Deal.objects.bulk_update(pending, ["number", "number_year", "number_seq"], batch_size=500)
    for year, value in last.items():
        Counter.objects.update_or_create(year=year, defaults={"last_value": value})


def clear(apps, schema_editor):
    Deal = apps.get_model("sales", "Deal")
    Counter = apps.get_model("sales", "DealNumberCounter")
    Deal.objects.update(number="", number_year=None, number_seq=None)
    Counter.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("sales", "0007_deal_number_process_auto_send")]

    operations = [migrations.RunPython(backfill, clear)]
