"""Вывод этапа KYC_PENDING из эксплуатации (решение владельца 2026-07-28).

Ресерч воронки показал: этап «KYC проверка» НИКОГДА не выставляется бизнес-логикой —
подача заявки без KYC просто отказывает (KYC_REQUIRED_TO_SUBMIT), KYC-статус живёт на
КОМПАНИИ (verification_status), а не на сделке. Мёртвая колонка воронки вводила в
заблуждение; попасть в неё можно было только ручным переносом.

Вывод из эксплуатации (никаких удалений — история и FK целы):
1. Строка справочника остаётся, но is_active=False → активные списки этапов
   (дропдаун/Канбан/воронка) её больше не показывают.
2. Сделки, застрявшие в KYC_PENDING (ручные переносы), возвращаются в DRAFT — иначе
   после скрытия колонки они стали бы невидимы на Канбане (тупик). DRAFT — их
   логичный дом: этап предшествовал подаче заявки.
3. Вход в этап убран из FSM (crm/services/deals.py), выходы сохранены.

Reverse: реактивирует строку (сделки остаются в DRAFT — безвредно).
"""

from django.db import migrations


def _retire(apps, schema_editor):
    deal_stage = apps.get_model("crm", "DealStage")
    deal = apps.get_model("crm", "Deal")
    kyc = deal_stage.objects.filter(code="KYC_PENDING").first()
    if kyc is None:
        return
    draft = deal_stage.objects.filter(code="DRAFT").first()
    if draft is not None:
        deal.objects.filter(stage=kyc).update(stage=draft)
    kyc.is_active = False
    kyc.save(update_fields=["is_active"])


def _revive(apps, schema_editor):
    deal_stage = apps.get_model("crm", "DealStage")
    deal_stage.objects.filter(code="KYC_PENDING").update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0076_fix_deal_stage_order"),
    ]

    operations = [
        migrations.RunPython(_retire, _revive),
    ]
