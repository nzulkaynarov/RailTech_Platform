"""Вывод KYC_PENDING из воронки (решение владельца 28-07).

KYC — свойство компании, не этап сделки: бизнес-логика этап никогда не ставила. Вывод
из эксплуатации без тупиков: входа нет, выходы есть, застрявшие сделки уехали в DRAFT,
активные списки этапов ряд не отдают, строка и история целы.
"""

import pytest

from crm.services.deals import get_allowed_transitions


def test_no_stage_leads_into_kyc_pending():
    from crm.services.deals import ALLOWED_STAGE_TRANSITIONS

    for source, targets in ALLOWED_STAGE_TRANSITIONS.items():
        assert "KYC_PENDING" not in targets, f"{source} всё ещё ведёт в выведенный этап"


def test_kyc_pending_straggler_can_always_exit():
    # Сделка, оказавшаяся в этапе исторически, не заперта: выходы сохранены.
    exits = get_allowed_transitions("KYC_PENDING")
    assert "RFQ_OPEN" in exits and "CLOSED_LOST" in exits


@pytest.mark.django_db
def test_active_stage_list_hides_retired_stage(django_user_model):
    from rest_framework.test import APIClient

    from crm.models import DealStage

    DealStage.objects.update_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    DealStage.objects.update_or_create(
        code="KYC_PENDING", defaults={"name": "KYC", "sort_order": 20, "is_active": False}
    )
    user = django_user_model.objects.create_user(email="s@x.uz", username="s@x.uz", password="pw", is_active=True)
    api = APIClient()
    api.force_authenticate(user=user)
    response = api.get("/api/v1/crm/deal-stages/")
    codes = [row["code"] for row in response.json()]
    assert "DRAFT" in codes
    assert "KYC_PENDING" not in codes  # дропдаун/Канбан/воронка больше не видят мёртвый этап
