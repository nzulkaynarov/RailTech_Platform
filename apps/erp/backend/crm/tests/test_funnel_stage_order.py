"""Ресерч воронки 2026-07-28: порядок этапов — один канон, воронка не врёт.

Root cause бага «Заявка открыта в конце воронки»: три источника sort_order жили своей
жизнью (ранний сид 0-7 без RFQ_OPEN, миграция 0002 с get_or_create, который существующие
строки не чинит, и dev-сид core_seed, перетиравший порядок при каждом запуске). Теперь
канон один — DEAL_STAGE_CANONICAL_ORDER (crm/constants); его принудительно накатывает
миграция crm/0076 и читает core_seed. Эти guard-тесты не дают источникам разъехаться снова.
"""

import pytest

from crm.constants import DEAL_STAGE_CANONICAL_ORDER, DealStageCode
from crm.services.deals import ALLOWED_STAGE_TRANSITIONS


def test_canonical_order_covers_every_stage_code_exactly_once():
    assert set(DEAL_STAGE_CANONICAL_ORDER) == set(DealStageCode)
    orders = list(DEAL_STAGE_CANONICAL_ORDER.values())
    assert len(orders) == len(set(orders)), "два этапа с одинаковым sort_order — порядок недетерминирован"


def test_canonical_order_follows_the_funnel():
    """Воронка слева направо: черновик → KYC → заявка → подбор → расчёт → КП → договор → закрытия.
    «Заявка открыта» обязана стоять ДО рабочих этапов продавца — именно это было сломано."""
    ordered = sorted(DEAL_STAGE_CANONICAL_ORDER, key=DEAL_STAGE_CANONICAL_ORDER.get)
    assert ordered == [
        DealStageCode.DRAFT,
        DealStageCode.KYC_PENDING,
        DealStageCode.RFQ_OPEN,
        DealStageCode.SOURCING,
        DealStageCode.CALCULATING,
        DealStageCode.QUOTE_SENT,
        DealStageCode.CONTRACT_SIGNED,
        DealStageCode.CLOSED_WON,
        DealStageCode.CLOSED_LOST,
    ]


def test_fsm_matrix_and_canon_speak_the_same_codes():
    """FSM-матрица переходов и канон порядка не могут знать разные наборы этапов."""
    fsm_codes = set(ALLOWED_STAGE_TRANSITIONS) | {
        code for targets in ALLOWED_STAGE_TRANSITIONS.values() for code in targets
    }
    assert fsm_codes <= set(DEAL_STAGE_CANONICAL_ORDER)


@pytest.mark.django_db
def test_core_seed_writes_canonical_order(settings):
    """Dev-сид больше не перетирает порядок своим списком — он читает канон."""
    from django.core.management import call_command

    settings.DEBUG = True  # core_seed — dev-сидер, в тестах эмулируем dev-окружение

    from crm.models import DealStage

    # Смоделировать «старую» БД со сломанным порядком.
    DealStage.objects.update_or_create(code="RFQ_OPEN", defaults={"name": "Заявка открыта", "sort_order": 25})
    DealStage.objects.update_or_create(code="SOURCING", defaults={"name": "Подбор", "sort_order": 2})
    call_command("core_seed")
    by_code = dict(DealStage.objects.values_list("code", "sort_order"))
    for code, expected in DEAL_STAGE_CANONICAL_ORDER.items():
        assert by_code[str(code)] == expected, f"{code}: {by_code[str(code)]} != {expected}"
