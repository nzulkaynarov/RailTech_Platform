"""Обзор «Внешние интеграции» (W13-A1): карточки со статусом пятью уровнями и «Требует внимания».

BFF не проверяет сервисы: уровни приходят из реестра внешних сервисов CRM (ADR-0024 CRM) и
ответов CRM, а здесь — свод. Тесты проверяют правила свода и поведение при частичных данных:
нет права в CRM или CRM не ответила — карточка помечается, обзор не падает; не ответила целиком —
503.
"""

from typing import Any

import pytest

from app.integrations_overview import worst
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.integrations_support import (
    CrmIntegrationsFake,
    backups,
    erp_status,
    mail_row,  # noqa: F401 — для читаемости импорта набора билдеров
    model_row,
    service,
    services_out,
    spend,
    system_status,
    telegram_status,
)

URL = "/api/v1/admin/integrations"


@pytest.fixture
def crm(be: Backends) -> CrmIntegrationsFake:
    return CrmIntegrationsFake(be)


def cards(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["key"]: c for c in body["cards"]}


def healthy_services() -> dict[str, Any]:
    return services_out(
        [
            service("telegram"),
            service("mail", fix_path="/integrations?tab=mail", switch=None),
            service("erp_sync", fix_path="/integrations?tab=erp"),
            service("erp_handoff"),
            service("erp_events"),
            service("litellm", fix_path="/models"),
            service("vendor.anthropic", fix_path="/models"),
            service("s3"),
            service("backup", fix_path="/backups"),
        ]
    )


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        (["ok", "ok"], "ok"),
        (["ok", "warn"], "warn"),
        (["warn", "fail", "ok"], "fail"),
        (["ok", "unknown"], "unknown"),
        (["unknown", "warn"], "warn"),
        (["off", "ok"], "ok"),
        (["off", "off"], "off"),
        ([], "off"),
        (["off", "unknown"], "unknown"),
    ],
)
def test_worst_level_ignores_off_and_ranks_fail_first(levels: list[Any], expected: str) -> None:
    assert worst(levels) == expected


async def test_everything_in_order_has_no_attention(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    await web.login(["ADMIN"])

    response = await web.client.get(URL)

    assert response.status_code == 200
    check(response, "/admin/integrations", "get")
    body = response.json()
    assert [c["key"] for c in body["cards"]] == [
        "erp",
        "telegram",
        "mail",
        "services",
        "models",
        "spend",
        "storage",
        "system",
    ]
    assert {c["status"] for c in body["cards"]} == {"ok"}
    assert {c["note"] for c in body["cards"]} == {"all_ok"}
    assert {c["access"] for c in body["cards"]} == {"ok"}
    assert body["attention"] == []
    by_key = cards(body)
    assert by_key["spend"]["amount_usd"] == 1.5
    assert by_key["system"]["last_activity_at"] == "2026-10-26T09:00:00Z"
    assert by_key["storage"]["last_activity_at"] == "2026-10-26T09:00:00Z"
    assert by_key["erp"]["last_activity_at"] == "2026-10-26T09:00:00Z"
    # одна сводка — несколько вызовов CRM параллельно, каждый от имени сотрудника
    assert len(crm.calls) == 7


async def test_problems_are_ordered_fail_then_warn_then_setup(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "admin/external-services",
        200,
        services_out(
            [
                service("telegram", "fail"),
                service("mail", "off", fix_path="/integrations?tab=mail", switch=None),
                service("erp_sync", "warn", fix_path="/integrations?tab=erp"),
                service("litellm", "ok", fix_path="/models"),
                service("s3", "ok"),
            ]
        ),
    )
    crm.answer("GET", "integrations/erp", 200, erp_status(configured=False, paired=False))
    crm.answer(
        "GET", "integrations/telegram", 200, telegram_status(running=False, last_error="409")
    )
    crm.answer(
        "GET", "models", 200, [model_row("dialog-model", "problem"), model_row("embed-model")]
    )
    crm.answer("GET", "system/backups", 200, backups(stale=True))
    crm.answer("GET", "system/status", 200, system_status("fail"))
    crm.answer(
        "GET",
        "spend",
        200,
        spend(providers=[{"provider": "anthropic", "spent_usd": 9.0, "limit_usd": 10.0}]),
    )
    await web.login(["ADMIN"])

    response = await web.client.get(URL)

    check(response, "/admin/integrations", "get")
    body = response.json()
    assert [(a["severity"], a["id"]) for a in body["attention"]] == [
        ("fail", "service:telegram"),
        ("fail", "model:dialog-model"),
        ("fail", "component:bot"),
        ("warn", "service:erp_sync"),
        ("warn", "bot:telegram"),
        ("warn", "backup:stale"),
        ("warn", "budget:anthropic"),
        ("setup", "setup:erp"),
        ("setup", "setup:mail"),
    ]
    first = body["attention"][0]
    assert first["card"] == "telegram"
    assert first["kind"] == "service"
    assert first["subject"] == "Telegram Bot API"
    assert first["detail"] == "Проверка не прошла. Проверьте токен бота"
    by_key = cards(body)
    assert (by_key["telegram"]["status"], by_key["telegram"]["note"]) == ("fail", "problems")
    assert (by_key["erp"]["status"], by_key["erp"]["note"]) == ("off", "not_configured")
    assert (by_key["mail"]["status"], by_key["mail"]["note"]) == ("off", "not_configured")
    assert by_key["models"]["status"] == "fail"
    assert by_key["models"]["count"] == 1
    assert (by_key["storage"]["status"], by_key["storage"]["note"]) == ("warn", "backup_stale")
    assert (by_key["system"]["status"], by_key["system"]["count"]) == ("fail", 1)
    assert (by_key["spend"]["status"], by_key["spend"]["note"]) == ("warn", "budget_near")
    assert (by_key["services"]["status"], by_key["services"]["count"]) == ("fail", 2)


async def test_budget_over_is_fail(web: Web, crm: CrmIntegrationsFake) -> None:
    crm.answer(
        "GET",
        "spend",
        200,
        spend(providers=[{"provider": "openai", "spent_usd": 11.0, "limit_usd": 10.0}]),
    )
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert (cards(body)["spend"]["status"], cards(body)["spend"]["note"]) == ("fail", "budget_over")
    item = next(a for a in body["attention"] if a["kind"] == "budget_over")
    assert item["detail"] == "11.00 / 10.00 USD"


async def test_manually_paused_service_is_attention_not_error(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    paused = service("mail", "ok", fix_path="/integrations?tab=mail")
    paused["switch"] = {**paused["switch"], "kind": "mail", "disabled": True, "reason": "ремонт"}
    crm.answer("GET", "admin/external-services", 200, services_out([service("telegram"), paused]))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert (cards(body)["mail"]["status"], cards(body)["mail"]["note"]) == ("ok", "paused")
    assert [(a["kind"], a["card"], a["detail"]) for a in body["attention"]] == [
        ("paused", "mail", "ремонт")
    ]
    assert cards(body)["services"]["note"] == "paused"


async def test_rotation_pending_is_a_warning_on_the_erp_card(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    crm.answer("GET", "integrations/erp", 200, erp_status(rotation_pending=True))
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert cards(body)["erp"]["note"] == "rotation_pending"
    assert [a["kind"] for a in body["attention"]] == ["rotation_pending"]


async def test_director_without_models_and_backups_still_gets_the_overview(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    """У директора в CRM нет `models:read` и `backups:read`: карточки — по тому, что CRM отдала."""
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    crm.error("GET", "models", 403, "forbidden")
    crm.error("GET", "system/backups", 403, "forbidden")
    crm.error("GET", "spend", 403, "forbidden")
    await web.login(["DIRECTOR"])

    response = await web.client.get(URL)

    assert response.status_code == 200
    check(response, "/admin/integrations", "get")
    by_key = cards(response.json())
    assert by_key["spend"]["access"] == "forbidden"
    assert by_key["spend"]["status"] == "unknown"
    assert by_key["spend"]["note"] == "no_data"
    assert by_key["models"]["access"] == "ok"
    assert by_key["storage"]["access"] == "ok"
    assert by_key["models"]["status"] == "ok"


async def test_one_part_down_marks_only_its_cards(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.answer("GET", "system/status", 500, {"code": "x", "message": "x", "details": {}})
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    await web.login(["ADMIN"])

    response = await web.client.get(URL)

    assert response.status_code == 200
    check(response, "/admin/integrations", "get")
    assert cards(response.json())["system"]["access"] == "unavailable"
    assert cards(response.json())["telegram"]["access"] == "ok"


async def test_crm_down_entirely_is_503(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    for path in (
        "admin/external-services",
        "system/status",
        "integrations/erp",
        "integrations/telegram",
        "models",
        "system/backups",
        "spend",
    ):
        crm.answer("GET", path, 503, {"code": "x", "message": "x", "details": {}})

    response = await web.client.get(URL)

    assert response.status_code == 503
    check(response, "/admin/integrations", "get")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


async def test_overview_is_read_only_and_needs_admin_read(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    await web.login(["MANAGER"])

    response = await web.client.get(URL)

    assert response.status_code == 403
    assert crm.count == 0
    assert (await web.send("POST", URL, json={})).status_code == 405
