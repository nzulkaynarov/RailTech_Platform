"""«Правда о состоянии» (НАСТ-П1, аудит Настроек §6.2): слово «Работает» только по живой проверке.

Таблица `resolve` — правила модели статуса; таблицы «часть не ответила → не удалось проверить
и строка в «Требует внимания»» — по карточкам «Сервисов» и по шине; «Почта» включает приём;
«Состояние» и «Сервисы» читают один ответ.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.status_model import STALE_AFTER, resolve
from tests.backends import Backends
from tests.bus_journal_support import BusDomainsFake, overview, subscriber
from tests.conftest import ContractChecker, Web
from tests.integrations_support import (
    CrmIntegrationsFake,
    group,
    service,
    services_out,
    system_status,
)
from tests.test_integrations_overview import cards, healthy_services

URL = "/api/v1/admin/integrations"
BUS = "/api/v1/admin/bus"
NOW = datetime(2026, 10, 26, 9, 5, tzinfo=UTC)
FRESH = NOW - timedelta(minutes=5)
OLD = NOW - STALE_AFTER - timedelta(minutes=1)


@pytest.fixture
def crm(be: Backends) -> CrmIntegrationsFake:
    return CrmIntegrationsFake(be)


# --- правила модели ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "probes", "kwargs", "state", "live"),
    [
        ("ok", [FRESH], {}, "works", True),
        ("ok", [FRESH, FRESH], {}, "works", True),
        ("ok", [], {}, "not_verified", False),  # настроено, проверки не было
        ("ok", [None], {}, "not_verified", False),
        ("ok", [FRESH, None], {}, "not_verified", False),  # одна из частей не проверена
        ("ok", [OLD], {}, "stale", False),  # проверка старше порога
        ("ok", [FRESH, OLD], {}, "stale", False),
        ("ok", [FRESH], {"stale": True}, "stale", False),  # CRM сама пометила проверку устаревшей
        ("ok", [FRESH], {"complete": False}, "unknown", False),  # часть данных не пришла
        ("unknown", [FRESH], {}, "unknown", False),
        ("warn", [FRESH], {}, "attention", True),
        ("fail", [OLD], {}, "broken", True),  # найденная проблема не «устаревает» в «Работает»
        ("fail", [FRESH], {"complete": False}, "broken", True),  # неполный ответ не прячет сбой
        ("off", [FRESH], {}, "off", False),
    ],
)
def test_resolve_table(
    level: Any, probes: list[datetime | None], kwargs: dict[str, Any], state: str, live: bool
) -> None:
    fact = resolve(level, probes=probes, now=NOW, **kwargs)
    assert (fact.state, fact.live) == (state, live)
    if fact.state == "works":
        assert fact.checked_at == min(p for p in probes if p is not None)


def test_works_needs_a_check_time_and_a_source() -> None:
    fact = resolve("ok", probes=[FRESH], now=NOW)
    assert fact.checked_at == FRESH
    assert fact.source == "check"
    assert resolve("ok", probes=[], now=NOW).source == "counters"
    assert resolve("ok", probes=[NOW], now=NOW, source="report").source == "report"


# --- карточки «Сервисов»: часть не ответила ------------------------------------------------

# часть CRM, которая не ответила -> карточки, у которых без неё «Работает» невозможно
DOWN: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "admin/external-services",
        "GET",
        ("erp", "telegram", "mail", "services", "models", "storage"),
    ),
    ("system/status", "GET", ("erp", "system")),
    ("integrations/erp", "GET", ("erp",)),
    ("integrations/telegram", "GET", ("telegram",)),
    ("models", "GET", ("models",)),
    ("system/backups", "GET", ("storage",)),
    ("spend", "GET", ("spend",)),
)


@pytest.mark.parametrize(("path", "method", "affected"), DOWN, ids=[d[0] for d in DOWN])
async def test_part_did_not_answer_means_unknown_and_a_row_in_attention(
    web: Web,
    crm: CrmIntegrationsFake,
    check: ContractChecker,
    path: str,
    method: str,
    affected: tuple[str, ...],
) -> None:
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    crm.answer(method, path, 503, {"code": "down", "message": "down", "details": {}})
    await web.login(["ADMIN"])

    response = await web.client.get(URL)

    assert response.status_code == 200
    check(response, "/admin/integrations", "get")
    body = response.json()
    by_key = cards(body)
    for key in affected:
        card = by_key[key]
        assert card["fact"]["state"] == "unknown", key
        assert card["fact"]["live"] is False, key
        assert card["status"] == "unknown", key
        assert card["note"] != "all_ok", key
    # «Требует внимания» не пусто и называет каждую карточку, которую не удалось проверить
    failed = {a["card"] for a in body["attention"] if a["kind"] == "check_failed"}
    assert failed >= set(affected)
    assert body["attention"] != []
    # остальные карточки не страдают
    untouched = set(by_key) - set(affected)
    assert all(by_key[key]["fact"]["state"] != "unknown" for key in untouched)


async def test_partial_answer_never_says_works_even_when_nothing_is_broken(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    """Л-27: CRM ответила не всё — «Всё в порядке» нет на карточках, зависящих от пропавшего."""
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    crm.answer("GET", "models", 500, {"code": "x", "message": "x", "details": {}})
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert cards(body)["models"]["fact"]["state"] == "unknown"
    assert "all_ok" not in {c["note"] for c in body["cards"] if c["fact"]["state"] != "works"}
    assert [a["id"] for a in body["attention"]] == ["check:models"]


async def test_forbidden_part_is_not_a_failed_check(web: Web, crm: CrmIntegrationsFake) -> None:
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    crm.error("GET", "models", 403, "forbidden")
    await web.login(["DIRECTOR"])

    body = (await web.client.get(URL)).json()

    assert all(a["kind"] != "check_failed" for a in body["attention"])


# --- «Настроено, не проверено» и «Нет свежих данных» ---------------------------------------


async def test_saved_but_never_checked_erp_is_not_verified(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    """Л-04/Л-31: адрес и ключи есть, проверки связи нет — «Настроено, не проверено»."""
    status = system_status("ok")
    status["components"] = [c for c in status["components"] if c["key"] != "erp"]
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    crm.answer("GET", "system/status", 200, status)
    await web.login(["ADMIN"])

    card = cards((await web.client.get(URL)).json())["erp"]

    assert card["fact"] == {
        "state": "not_verified",
        "checked_at": None,
        "source": "counters",
        "live": False,
    }
    assert (card["status"], card["note"]) == ("unknown", "not_verified")


async def test_old_check_is_stale_not_green(web: Web, crm: CrmIntegrationsFake) -> None:
    old = (NOW - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    rows = [
        service("telegram", checked_at=old),
        service("mail", checked_at=old, switch=None),
        service("erp_sync"),
        service("litellm"),
        service("s3"),
        service("backup"),
    ]
    crm.answer("GET", "admin/external-services", 200, services_out(rows))
    await web.login(["ADMIN"])

    by_key = cards((await web.client.get(URL)).json())

    for key in ("telegram", "mail"):
        assert by_key[key]["fact"]["state"] == "stale", key
        assert by_key[key]["note"] == "stale", key
        assert by_key[key]["fact"]["checked_at"] == old
    assert by_key["models"]["fact"]["state"] == "works"


# --- «Почта» включает приём ------------------------------------------------------------------


async def test_mail_tile_includes_inbound_polling_and_matches_the_list(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    """Плитка «Почта» не говорит «Работает» рядом с «Ящик давно не опрашивался»."""
    inbound = service("mail_inbound", "warn", fix_path="/integrations?tab=mail", switch=None)
    inbound.update(
        state="degraded", summary="Ящик давно не опрашивался", cause_key="mail_inbound:stale"
    )
    rows = [*healthy_services()["services"], inbound]
    groups = [
        group(
            "mail_inbound",
            "degraded",
            id="mail_inbound:stale",
            headline="Ящик давно не опрашивался",
            detail="Проверьте приём почты",
        )
    ]
    crm.answer("GET", "admin/external-services", 200, services_out(rows, groups))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    mail = cards(body)["mail"]
    assert mail["fact"]["state"] == "attention"
    assert (mail["status"], mail["note"], mail["count"]) == ("warn", "problems", 1)
    assert [a["card"] for a in body["attention"]] == ["mail"]


# --- одна дата проверки и один ответ ------------------------------------------------------


async def test_one_check_date_per_card_equals_the_fact(web: Web, crm: CrmIntegrationsFake) -> None:
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    for card in body["cards"]:
        assert card["last_activity_at"] == card["fact"]["checked_at"], card["key"]


async def test_state_and_services_read_the_same_fact(web: Web, crm: CrmIntegrationsFake) -> None:
    """«Один факт — один ответ»: «Состояние» и «Сервисы» берут карточку из одного ответа."""
    crm.answer("GET", "admin/external-services", 200, healthy_services())
    await web.login(["ADMIN"])

    first = (await web.client.get(URL)).json()
    second = (await web.client.get(URL)).json()

    assert first == second
    assert {c["key"]: c["fact"] for c in first["cards"]}["mail"]["state"] == "works"


# --- шина ----------------------------------------------------------------------------------


@pytest.fixture
def domains(be: Backends) -> BusDomainsFake:
    return BusDomainsFake(be)


async def test_bus_with_every_domain_answering_works(
    web: Web, domains: BusDomainsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(BUS)

    check(response, "/admin/bus", "get")
    fact = response.json()["fact"]
    assert (fact["state"], fact["live"], fact["source"]) == ("works", True, "check")


@pytest.mark.parametrize("silent", ["crm", "erp", "eds"])
async def test_bus_domain_that_did_not_answer_is_unknown_not_works(
    web: Web, domains: BusDomainsFake, silent: str
) -> None:
    """Л-05/Л-34: не ответивший домен не выпадает из сумм молча — «Не удалось проверить»."""
    domains.answer(silent, "GET", "overview", {"detail": "down"}, 503)
    await web.login(["ADMIN"])

    body = (await web.client.get(BUS)).json()

    assert body["sources"][silent] == "unavailable"
    assert body["fact"]["state"] == "unknown"
    assert body["fact"]["live"] is False


async def test_bus_dead_letters_are_broken_even_when_a_domain_is_silent(
    web: Web, domains: BusDomainsFake
) -> None:
    domains.answer("crm", "GET", "overview", overview("crm", [subscriber("erp", dead=2)]))
    domains.answer("eds", "GET", "overview", {"detail": "down"}, 503)
    await web.login(["ADMIN"])

    assert (await web.client.get(BUS)).json()["fact"]["state"] == "broken"


# --- плитка и список не расходятся (по fix_card строки) -----------------------------------

FIX_PATHS = {
    "erp": "/integrations?tab=erp",
    "telegram": "/integrations?tab=bot",
    "mail": "/integrations?tab=mail",
    "models": "/models",
    "storage": "/backups",
}


@pytest.mark.parametrize("card", list(FIX_PATHS))
async def test_every_attention_row_points_at_a_card_that_is_not_green(
    web: Web, crm: CrmIntegrationsFake, card: str
) -> None:
    """Сервис с любым ключом, чей `fix_path` ведёт на карточку, не может оставить её «Работает»."""
    broken = service(f"{card}.extra_probe", "fail", fix_path=FIX_PATHS[card], switch=None)
    broken.update(state="broken", owner="admin", action="open_settings")
    rows = [*healthy_services()["services"], broken]
    groups = [group(f"{card}.extra_probe", "broken", id=f"{card}.extra_probe:down")]
    crm.answer("GET", "admin/external-services", 200, services_out(rows, groups))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    rows_for_card = [a for a in body["attention"] if a["card"] == card]
    assert rows_for_card, "строка «Требует внимания» должна вести на карточку"
    for attention in body["attention"]:
        state = cards(body)[attention["card"]]["fact"]["state"]
        assert state not in ("works", "off"), (attention["id"], state)


# --- «ещё не использовался» — не «сервер не ответил» ---------------------------------------


def never_used(key: str, fix_path: str) -> dict[str, Any]:
    row = service(key, "unknown", fix_path=fix_path, switch=None)
    row.update(
        state="not_checked", summary="Данных пока нет — сервис ещё не использовался", error=None
    )
    return row


async def test_never_used_service_does_not_lower_the_tile_or_add_a_row(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    rows = [
        *healthy_services()["services"],
        never_used("erp.rates", "/integrations?tab=erp"),
        never_used("erp.banks", "/integrations?tab=erp"),
    ]
    crm.answer("GET", "admin/external-services", 200, services_out(rows))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    by_key = cards(body)
    for key in ("erp", "services"):
        assert by_key[key]["fact"]["state"] == "works", key
        assert by_key[key]["note"] == "all_ok", key
    assert not [a for a in body["attention"] if a["kind"] == "check_failed"]


async def test_real_silence_of_a_service_is_unknown_with_a_row(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    silent = service("erp.rates", "unknown", fix_path="/integrations?tab=erp", switch=None)
    silent.update(state="ok", checked_at=None)
    rows = [*healthy_services()["services"], silent]
    crm.answer("GET", "admin/external-services", 200, services_out(rows))
    await web.login(["ADMIN"])

    body = (await web.client.get(URL)).json()

    assert cards(body)["erp"]["fact"]["state"] == "unknown"
    assert "check:erp" in [a["id"] for a in body["attention"]]
