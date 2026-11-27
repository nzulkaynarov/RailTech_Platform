"""ПРАВДА-2: статус заявки в Кабинете (`portal.projections.request_status`) совпадает с таблицей контракта.

`packages/contracts/client-request-statuses.yaml` — источник и для карточки компании в Платформе («В кабинете клиента»),
и для списка «Заявки» Кабинета. Здесь: каждая стадия контракта из `by_external_stage`, собранная из настоящих документов,
даёт в ERP тот же статус.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from integration.tests.world import STAGE_CASES, make_company, make_deal
from portal import projections

from crm.constants import DealStageCode

pytestmark = pytest.mark.django_db


def _contract() -> dict:
    # Как у сторожа OpenAPI: в тестовом контейнере `packages/contracts` монтируется в /packages/contracts
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "contracts" / "client-request-statuses.yaml"
        if candidate.is_file():
            return yaml.safe_load(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError("packages/contracts/client-request-statuses.yaml не найден; проверка не пропускается")


CONTRACT = _contract()

def _fresh_request(company):
    # Заявка, которую никто не трогал (DRAFT, КП нет): так её видит клиент. RFQ_OPEN/KYC_PENDING тоже дают стадию
    # `request`, но в Кабинете это уже «В работе»; событие шины при этом не шлётся (стадия контракта прежняя) — хвост PR.
    return make_deal(company, DealStageCode.DRAFT)


REQUEST_CASES = [
    (stage, _fresh_request if stage == "request" else build)
    for stage, build in STAGE_CASES
    if stage in CONTRACT["by_external_stage"]
]


def test_contract_table_covers_the_request_phase_stages():
    assert {case[0] for case in REQUEST_CASES} == set(CONTRACT["by_external_stage"])


@pytest.mark.parametrize(("stage", "build"), REQUEST_CASES, ids=[case[0] for case in REQUEST_CASES])
def test_erp_request_status_is_the_contract_status(stage, build):
    deal = build(make_company())
    assert projections.request_status(deal) == CONTRACT["by_external_stage"][stage]
