"""Волна 12 (EDS-03), данные: шаги «Руководитель» прежней цепочки одобрения КП удаляются.

Своей цепочки одобрения директором у ERP больше нет (решение архитектора волны 12 §4 п. 3): одобряет директор в EDS.
КП, ждавшее только руководителя (других открытых шагов нет), возвращается в черновик (курс снова живой) — повторная
отправка уйдёт директору в EDS. Отдельно от схемы 0005: на PostgreSQL изменение строк с триггерами pghistory и ALTER
TABLE в одной транзакции дают «pending trigger events». Обратного хода нет.
"""

from django.db import migrations


def drop_head_steps(apps, schema_editor):
    QuoteApprovalStep = apps.get_model("sales", "QuoteApprovalStep")
    Quote = apps.get_model("sales", "Quote")
    QuoteStatus = apps.get_model("sales", "QuoteStatus")
    head = QuoteApprovalStep.objects.filter(participation="HEAD")
    waiting = set(head.filter(status="PENDING").values_list("quote_id", flat=True))
    head.delete()
    draft = QuoteStatus.objects.filter(code="DRAFT").first()
    if draft is None or not waiting:
        return
    for quote in Quote.objects.filter(pk__in=waiting, status__code="PENDING_APPROVAL"):
        acting = QuoteApprovalStep.objects.filter(quote=quote, status="PENDING").exclude(participation="INFORMED")
        if not acting.exists():
            quote.status = draft
            quote.fx_fixed_at = None
            quote.save(update_fields=["status", "fx_fixed_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0005_eds_calc_tasks_director_decision"),
    ]

    operations = [
        migrations.RunPython(drop_head_steps, migrations.RunPython.noop),
    ]
