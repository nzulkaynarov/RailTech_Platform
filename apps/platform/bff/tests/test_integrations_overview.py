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
    group,
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
    # «бот не запущен» и «Бот» из состояния системы — та же беда, что строка Telegram
    assert [(a["severity"], a["id"]) for a in body["attention"]] == [
        ("fail", "group:telegram:status"),
        ("fail", "model:dialog-model"),
        ("warn", "group:erp_sync:status"),
        ("warn", "backup:stale"),
        ("warn", "budget:anthropic"),
        ("setup", "setup:erp"),
        ("setup", "setup:mail"),
    ]
    first = body["attention"][0]
    assert first["card"] == "telegram"
    assert first["kind"] == "service"
    assert first["subject"] == "Проверка не прошла"
    assert first["detail"] == "Проверьте токен бота"
    assert first["group"]["owner"] == "admin"
    assert first["group"]["since"] == "2026-10-26T08:55:00Z"
    model = body["attention"][1]
    assert model["detail"] is None
    assert model["technical"] == "401 от провайдера"  # сырой текст — отдельным полем, не в detail
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


def key_rejected_group(**over: Any) -> dict[str, Any]:
    return group(
        "vendor.anthropic",
        "broken",
        id="vendor.anthropic:key_rejected",
        owner="owner",
        action="enter_key",
        more_actions=["write_owner", "disable_provider"],
        headline="Ключ Anthropic отклонён",
        detail="Ключ провайдера отклонён — введите новый ключ в «Модели ИИ»",
        affected=["диалог с клиентом", "запасная модель", "поиск по базе знаний"],
        technical=["401 AuthenticationError"],
        message="Здравствуйте! Нужен новый ключ.",
        **over,
    )


async def test_one_cause_is_one_row_not_five(web: Web, crm: CrmIntegrationsFake) -> None:
    """Ключ отклонён: вендор, три роли моделей, их компоненты и расходы — одна строка, не пять."""
    vendor = service("vendor.anthropic", "fail", fix_path="/models")
    vendor.update(state="broken", owner="owner", action="enter_key")
    crm.answer(
        "GET",
        "admin/external-services",
        200,
        services_out([vendor, service("s3")], [key_rejected_group()]),
    )
    crm.answer(
        "GET",
        "models",
        200,
        [
            model_row("dialog-model", "problem"),
            model_row("fallback-model", "problem"),
            model_row("embed-model", "problem"),
        ],
    )
    status = system_status("ok")
    status["components"] += [
        {
            "key": f"model:{alias}",
            "title": f"Модель ИИ: {alias}",
            "status": "fail",
            "reason": "401 от провайдера",
            "checked_at": "2026-10-26T09:00:00Z",
            "expected_on_stand": False,
        }
        for alias in ("dialog-model", "fallback-model")
    ]
    crm.answer("GET", "system/status", 200, status)
    crm.answer(
        "GET",
        "spend",
        200,
        spend(providers=[{"provider": "anthropic", "spent_usd": 9.5, "limit_usd": 10.0}]),
    )
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    ids = [a["id"] for a in body["attention"]]
    assert ids == ["group:vendor.anthropic:key_rejected"]
    row = body["attention"][0]
    assert row["card"] == "models"  # «Ввести новый ключ» открывает форму в карточке «Модели ИИ»
    assert row["group"]["affected"] == [
        "диалог с клиентом",
        "запасная модель",
        "поиск по базе знаний",
    ]
    assert row["group"]["technical"] == ["401 AuthenticationError"]
    assert row["group"]["fix_card"] == "models"
    assert row["technical"] is None
    models_card = cards(body)["models"]
    assert (models_card["status"], models_card["count"]) == ("fail", 1)


async def test_expected_on_stand_is_not_attention_and_does_not_colour_cards(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    docling = service("docling", "fail")
    docling.update(state="expected", owner="hosting", action="recheck")
    token = service("telegram", "fail", fix_path="/integrations?tab=bot")
    token.update(state="expected", owner="admin", action="recheck")
    groups = [
        group("docling", "expected", id="docling:server_down", owner="hosting"),
        group("telegram", "expected", id="telegram:no_token"),
    ]
    crm.answer(
        "GET", "admin/external-services", 200, services_out([docling, token], groups, stand=True)
    )
    crm.answer("GET", "integrations/telegram", 200, telegram_status(configured=False))
    status = system_status("ok")
    status["components"].append(
        {
            "key": "secrets",
            "title": "Секреты сервера",
            "status": "fail",
            "reason": "Не заданы на сервере: TELEGRAM_BOT_TOKEN",
            "checked_at": "2026-10-26T09:00:00Z",
            "expected_on_stand": True,
        }
    )
    crm.answer("GET", "system/status", 200, status)
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert body["attention"] == []
    by_key = cards(body)
    assert by_key["services"]["status"] == "off"
    assert by_key["telegram"]["status"] == "off"
    assert by_key["services"]["count"] in (None, 0)


async def test_erp_not_connected_is_one_row_for_all_its_services(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    rows = [
        service(key, "off", state="not_configured", cause_key="erp:erp_not_connected")
        for key in ("erp_sync", "erp_handoff", "erp.mail")
    ]
    erp_group = group(
        "erp_sync",
        "not_configured",
        id="erp:erp_not_connected",
        headline="ERP не подключена",
        service_keys=["erp_sync", "erp_handoff", "erp.mail"],
        action="reconnect",
    )
    crm.answer("GET", "admin/external-services", 200, services_out(rows, [erp_group]))
    crm.answer("GET", "integrations/erp", 200, erp_status(configured=False, paired=False))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert [a["id"] for a in body["attention"]] == ["group:erp:erp_not_connected"]
    assert body["attention"][0]["severity"] == "setup"


async def test_hosting_cause_keeps_the_ready_message_for_the_copy_button(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    docling = service("docling", "fail")
    docling.update(state="broken", owner="hosting", action="write_hosting")
    hosting = group(
        "docling",
        "broken",
        id="docling:server_down",
        owner="hosting",
        action="write_hosting",
        message="Запустить docling вместе с ансамблем",
    )
    crm.answer("GET", "admin/external-services", 200, services_out([docling], [hosting]))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    (row,) = [a for a in body["attention"] if a["id"].startswith("group:")]
    assert row["group"]["message"] == "Запустить docling вместе с ансамблем"
    assert row["group"]["action"] == "write_hosting"
    listing = (await web.client.get(f"{URL}/services")).json()
    assert listing["groups"][0]["id"] == "docling:server_down"
    assert listing["stand"] is False


async def test_unstable_is_a_yellow_warning_row_not_a_failure(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    flapping = service("docling", "ok", state="unstable", cause_key="docling:flapping", flaps_24h=6)
    flap_group = group(
        "docling",
        "unstable",
        id="docling:flapping",
        owner=None,
        action="recheck",
        more_actions=[],
        headline="docling: нестабильная связь, провалов за сутки: 6",
        flaps_24h=6,
    )
    crm.answer("GET", "admin/external-services", 200, services_out([flapping], [flap_group]))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    (row,) = [a for a in body["attention"] if a["id"].startswith("group:")]
    assert (row["severity"], row["group"]["state"], row["group"]["flaps_24h"]) == (
        "warn",
        "unstable",
        6,
    )
    assert cards(body)["services"]["status"] == "warn"


async def test_raw_bot_and_backup_errors_go_to_technical_not_detail(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    crm.answer(
        "GET", "integrations/telegram", 200, telegram_status(running=False, last_error="boom 401")
    )
    crm.answer("GET", "system/backups", 200, backups(stale=True, error="bucket_missing"))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    bot = next(a for a in body["attention"] if a["id"] == "bot:telegram")
    backup = next(a for a in body["attention"] if a["id"] == "backup:stale")
    assert (bot["detail"], bot["technical"]) == (None, "boom 401")
    assert (backup["detail"], backup["technical"]) == (None, "bucket_missing")
