"""Admin · Зоны ответственности (ЕВ-З): `/admin/responsibility-zones*` и карточка на Главной.

CRM — на respx (`/api/v1/responsibility-zones*`); ответы BFF сверяются со схемами контракта.
Проблемы зон, права и журнал — за CRM: здесь проверяются перевод в контракт, права разделов
(`admin` и `company.settings`) и то, что BFF сам ничего не решает.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.feeds_support import FeedBackends, Moments

ZONES = f"{CRM_URL}/api/v1/responsibility-zones"
NOW = "2026-11-23T09:00:00Z"


def person(user_id: int, name: str, *, active: bool = True) -> dict[str, Any]:
    return {"id": user_id, "name": name, "position": "Директор", "is_active": active}


def crm_zone(zone_id: int, code: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": zone_id,
        "code": code,
        "name": {"ru": "Финансы", "uz": "Moliya", "en": "Finance"},
        "description": {"ru": "Счета", "uz": "Hisoblar", "en": "Invoices"},
        "sections": ["eds.payments"],
        "responsible": None,
        "deputy": None,
        "curator": None,
        "basis": "",
        "valid_from": None,
        "valid_to": None,
        "is_active": True,
        "problems": [{"code": "no_responsible", "severity": "problem", "sections": []}],
        "updated_at": NOW,
        **extra,
    }


class CrmZones:
    """`/api/v1/responsibility-zones*` CRM в памяти: запоминает последние тела запросов."""

    def __init__(self, be: Backends) -> None:
        self.zones: dict[int, dict[str, Any]] = {
            1: crm_zone(1, "finance"),
            2: crm_zone(
                2,
                "legal",
                responsible=person(5, "Анна Демова"),
                problems=[
                    {
                        "code": "responsible_lacks_permissions",
                        "severity": "warning",
                        "sections": ["eds.visa.legal"],
                    }
                ],
            ),
        }
        self.bodies: list[dict[str, Any]] = []
        self.summary_body = {"zones_total": 2, "without_responsible": 1, "with_problems": 2}
        router = be.router
        self.list_route = router.get(ZONES).mock(
            side_effect=lambda r: httpx.Response(200, json={"items": list(self.zones.values())})
        )
        self.summary_route = router.get(f"{ZONES}/summary").mock(
            side_effect=lambda r: httpx.Response(200, json=self.summary_body)
        )
        self.create_route = router.post(ZONES).mock(side_effect=self._create)
        one = rf"{ZONES}/\d+$"
        self.get_route = router.get(url__regex=one).mock(side_effect=self._get)
        self.patch_route = router.patch(url__regex=one).mock(side_effect=self._patch)
        self.off_route = router.post(url__regex=rf"{ZONES}/\d+/deactivate$").mock(
            side_effect=lambda r: self._toggle(r, False)
        )
        self.on_route = router.post(url__regex=rf"{ZONES}/\d+/activate$").mock(
            side_effect=lambda r: self._toggle(r, True)
        )

    @staticmethod
    def _id(request: httpx.Request) -> int:
        parts = request.url.path.split("/")
        return int(parts[-1] if parts[-1].isdigit() else parts[-2])

    @staticmethod
    def _error(status: int, code: str, **details: Any) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "message": code, "details": details})

    def _get(self, request: httpx.Request) -> httpx.Response:
        zone = self.zones.get(self._id(request))
        return httpx.Response(200, json=zone) if zone else self._error(404, "not_found")

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if any(z["code"] == body["code"] for z in self.zones.values()):
            return self._error(409, "conflict", field="code")
        description = {"ru": "", "uz": "", "en": "", **body.get("description", {})}
        zone = crm_zone(
            9, body["code"], name=body["name"], description=description, sections=body["sections"]
        )
        self.zones[9] = zone
        return httpx.Response(201, json=zone)

    def _patch(self, request: httpx.Request) -> httpx.Response:
        zone = self.zones.get(self._id(request))
        if zone is None:
            return self._error(404, "not_found")
        body = json.loads(request.content)
        self.bodies.append(body)
        if not zone["is_active"]:
            return self._error(409, "conflict")
        zone.update({k: v for k, v in body.items() if not k.endswith("_user_id")})
        if body.get("responsible_user_id"):
            zone["responsible"] = person(body["responsible_user_id"], "Анна Демова")
            zone["problems"] = []
        return httpx.Response(200, json=zone)

    def _toggle(self, request: httpx.Request, active: bool) -> httpx.Response:
        zone = self.zones.get(self._id(request))
        if zone is None:
            return self._error(404, "not_found")
        zone["is_active"] = active
        return httpx.Response(200, json=zone)


@pytest.fixture
def zones(be: Backends) -> CrmZones:
    return CrmZones(be)


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    """Остальные источники Главной (EDS, ERP, CRM) — пустые ответы: карточки зон не мешают."""
    return FeedBackends(web.be.router, Moments(web.clock))


async def test_list_maps_zones_with_people_and_problems(
    web: Web, zones: CrmZones, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/admin/responsibility-zones")

    assert response.status_code == 200
    check(response, "/admin/responsibility-zones", "get")
    first, second = response.json()["items"]
    assert (first["id"], first["code"], first["active"]) == ("1", "finance", True)
    assert first["name"]["uz"] == "Moliya"
    assert "responsible" not in first
    assert first["problems"] == [{"code": "no_responsible", "severity": "problem"}]
    assert second["responsible"] == {
        "id": "5",
        "name": "Анна Демова",
        "position": "Директор",
        "active": True,
    }
    assert second["problems"][0]["sections"] == ["eds.visa.legal"]


@pytest.mark.parametrize("role", ["MANAGER", "ACCOUNTANT"])
async def test_roles_without_admin_section_get_nothing(
    web: Web, zones: CrmZones, check: ContractChecker, role: str
) -> None:
    await web.login([role])

    for url in ("", "/summary", "/1"):
        response = await web.client.get(f"/api/v1/admin/responsibility-zones{url}")
        assert response.status_code == 403, url
        check(response, f"/admin/responsibility-zones{url or ''}".replace("/1", "/{id}"), "get")
    assert not zones.list_route.called


async def test_director_assigns_people_but_cannot_create_or_deactivate(
    web: Web, zones: CrmZones, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    body = {"responsible_id": "5", "deputy_id": None, "basis": "Приказ № 5 от 01.12.2026"}
    patched = await web.send("PATCH", "/api/v1/admin/responsibility-zones/1", json=body)

    assert patched.status_code == 200, patched.text
    check(patched, "/admin/responsibility-zones/{id}", "patch")
    # id сотрудника уходит в CRM числом и под своим именем, `null` снимает значение.
    assert zones.bodies[-1] == {
        "responsible_user_id": 5,
        "deputy_user_id": None,
        "basis": "Приказ № 5 от 01.12.2026",
    }
    assert patched.json()["responsible"]["id"] == "5"
    assert patched.json()["problems"] == []

    created = await web.send(
        "POST",
        "/api/v1/admin/responsibility-zones",
        json={"code": "quality", "name": _name(), "sections": ["crm.clients"]},
    )
    off = await web.send("POST", "/api/v1/admin/responsibility-zones/1/deactivate")
    assert (created.status_code, off.status_code) == (403, 403)
    assert zones.create_route.call_count == 0
    assert zones.off_route.call_count == 0


def _name() -> dict[str, str]:
    return {"ru": "Качество", "uz": "Sifat", "en": "Quality"}


async def test_admin_creates_deactivates_and_activates(
    web: Web, zones: CrmZones, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    url = "/api/v1/admin/responsibility-zones"

    created = await web.send(
        "POST",
        url,
        json={"code": "quality", "name": _name(), "sections": ["crm.clients", "erp.stock"]},
    )
    again = await web.send(
        "POST", url, json={"code": "quality", "name": _name(), "sections": ["crm.clients"]}
    )
    off = await web.send("POST", f"{url}/1/deactivate")
    blocked = await web.send("PATCH", f"{url}/1", json={"basis": "x"})
    on = await web.send("POST", f"{url}/1/activate")

    assert created.status_code == 201
    check(created, "/admin/responsibility-zones", "post")
    assert zones.bodies[0]["sections"] == ["crm.clients", "erp.stock"]
    assert again.status_code == 409
    assert (off.status_code, off.json()["active"]) == (200, False)
    check(off, "/admin/responsibility-zones/{id}/deactivate", "post")
    assert blocked.status_code == 409
    assert (on.status_code, on.json()["active"]) == (200, True)
    check(on, "/admin/responsibility-zones/{id}/activate", "post")


async def test_bff_rejects_unknown_sections_and_bad_ids_before_crm(
    web: Web, zones: CrmZones
) -> None:
    await web.login(["ADMIN"])
    url = "/api/v1/admin/responsibility-zones"

    unknown = await web.send(
        "POST", url, json={"code": "q", "name": _name(), "sections": ["no.such"]}
    )
    empty = await web.send("POST", url, json={"code": "quality", "name": _name(), "sections": []})
    bad_id = await web.send("PATCH", f"{url}/1", json={"responsible_id": "abc"})
    reversed_term = await web.send(
        "PATCH", f"{url}/1", json={"valid_from": "2026-12-02", "valid_to": "2026-12-01"}
    )

    assert [r.status_code for r in (unknown, empty, bad_id, reversed_term)] == [422] * 4
    assert zones.create_route.call_count == 0
    assert zones.patch_route.call_count == 0


async def test_summary_for_company_settings_holders(
    web: Web, zones: CrmZones, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/admin/responsibility-zones/summary")

    assert response.status_code == 200
    check(response, "/admin/responsibility-zones/summary", "get")
    assert response.json() == zones.summary_body


# --- карточка на Главной ------------------------------------------------------------------------


def summary(without: int, total: int = 2) -> dict[str, int]:
    return {"zones_total": total, "without_responsible": without, "with_problems": without}


async def test_card_for_company_settings_holders_while_a_zone_has_no_responsible(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["crm_zones"] = summary(1)
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue/cards")

    check(response, "/queue/cards", "get")
    cards = response.json()["cards"]
    assert cards[0] == {
        "key": "zones_without_responsible",
        "label": "Зоны без ответственного",
        "count": 1,
        "hint": "Настройки · Люди и доступ · Зоны ответственности",
        "path": "/admin/zones",
    }


async def test_no_card_when_every_zone_has_a_responsible(web: Web, fb: FeedBackends) -> None:
    fb.state["crm_zones"] = summary(0)
    await web.login(["DIRECTOR"])

    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]

    assert "zones_without_responsible" not in [c["key"] for c in cards]
    assert fb.crm["zones"].called


async def test_no_card_and_no_request_for_roles_without_company_settings(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["crm_zones"] = summary(3)
    await web.login(["MANAGER"])

    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]

    assert "zones_without_responsible" not in [c["key"] for c in cards]
    assert not fb.crm["zones"].called


async def test_card_vanishes_quietly_when_crm_does_not_answer(web: Web, fb: FeedBackends) -> None:
    fb.state["crm_zones"] = (503, {"code": "unavailable", "message": "x", "details": {}})
    await web.login(["DIRECTOR"])

    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]

    assert "zones_without_responsible" not in [c["key"] for c in cards]
