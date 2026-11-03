"""EDS · Проект: отметки доставки «В пути / Доставлено» и файл подтверждения (L0-1).

ERP — на respx (`eds_projects_support`), ответы BFF — по схемам platform-bff.yaml. BFF не решает:
право `fulfillment.manage`, переход и поля проверяет ERP; здесь — раздел (`eds.projects` чтение),
форма multipart как есть, id сделки и файла — из карточки, а не из запроса, перевод отказов ERP и
поток файла как вложения.
"""

import re
from typing import Any

import httpx
import pytest

from app.eds_projects import _ERP_REASONS
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.eds_projects_support import DEAL, PDF, ProjectsFake, card, erp_error
from tests.roles import Role

BASE = "/api/v1/eds/projects"
NUMBER = "ПР-2026-104"


def fulfillment(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "SHIPPED",
        "status_name": "Отгружено",
        "expected_delivery_date": "2026-12-01",
        "shipped_at": "2026-10-28T10:00:00+05:00",
        "delivered_at": None,
        "accepted_at": None,
        "tracking_number": "",
        "carrier": "",
        "actions": ["in_transit", "delivered"],
        "proof_attachment_id": None,
        "proof_name": None,
    }
    return {**base, **over}


@pytest.fixture
def erp(be: Backends) -> ProjectsFake:
    fake = ProjectsFake(be)
    fake.cards[DEAL] = card(fulfillment=fulfillment())
    return fake


async def _as(web: Web, role: Role) -> None:
    assert (await web.login([role])).status_code == 200


def _form(**fields: str) -> dict[str, Any]:
    return {"data": fields, "files": {"file": ("pod.pdf", PDF, "application/pdf")}}


def _delivered_card() -> dict[str, Any]:
    return card(
        fulfillment=fulfillment(
            status="DELIVERED",
            status_name="Доставлено",
            delivered_at="2026-11-02T12:00:00+05:00",
            tracking_number="CMR-0042",
            actions=[],
            proof_attachment_id=77,
            proof_name="pod.pdf",
        )
    )


async def test_card_shows_actions_and_hides_the_file_id(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "SUPPLY")
    erp.cards[DEAL] = _delivered_card()
    response = await web.client.get(f"{BASE}/{NUMBER}")
    check(response, "/eds/projects/{ref}", "get")
    f = response.json()["fulfillment"]
    assert f["actions"] == []
    assert f["proof_name"] == "pod.pdf"
    assert f["proof_url"] == f"/api/v1/eds/projects/{NUMBER}/delivery/proof"
    assert "proof_attachment_id" not in f


async def test_card_without_proof_has_no_link(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "SUPPLY")
    f = (await web.client.get(f"{BASE}/{NUMBER}")).json()["fulfillment"]
    assert f["actions"] == ["in_transit", "delivered"]
    assert f["proof_name"] is None
    assert f["proof_url"] is None


@pytest.mark.parametrize("role", ["SUPPLY", "DIRECTOR", "MANAGER"])
async def test_mark_goes_to_the_erp_as_is_for_a_reader(
    web: Web, erp: ProjectsFake, check: ContractChecker, role: Role
) -> None:
    await _as(web, role)
    erp.answer("POST", rf"projects/{DEAL}/delivery/", httpx.Response(200, json=_delivered_card()))
    response = await web.client.post(
        f"{BASE}/{NUMBER}/delivery",
        headers={"X-CSRF-Token": web.csrf},
        **_form(action="delivered", on_date="2026-11-02", waybill="CMR-0042"),
    )
    check(response, "/eds/projects/{ref}/delivery", "post")
    assert response.json()["fulfillment"]["status"] == "DELIVERED"
    [call] = erp.calls_to("POST", rf"projects/{DEAL}/delivery/")
    assert call.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert PDF in call.content
    assert b"CMR-0042" in call.content
    assert call.headers["authorization"].startswith("Bearer ")


async def test_mark_needs_the_section_and_csrf(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ADMIN")  # у админа платформы раздела «Проекты» нет
    response = await web.client.post(
        f"{BASE}/{NUMBER}/delivery", headers={"X-CSRF-Token": web.csrf}, **_form(action="delivered")
    )
    assert response.status_code == 403
    await _as(web, "SUPPLY")
    response = await web.client.post(f"{BASE}/{NUMBER}/delivery", **_form(action="delivered"))
    assert response.status_code == 403
    assert erp.posts() == []


async def test_mark_must_be_multipart(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "SUPPLY")
    response = await web.send("POST", f"{BASE}/{NUMBER}/delivery", json={"action": "delivered"})
    assert response.status_code == 422
    assert erp.posts() == []


async def test_mark_on_a_wrong_year_number_is_not_found(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "SUPPLY")
    response = await web.client.post(
        f"{BASE}/ПР-2025-104/delivery",
        headers={"X-CSRF-Token": web.csrf},
        **_form(action="delivered"),
    )
    assert response.status_code == 404
    assert erp.posts() == []


@pytest.mark.parametrize(
    ("status", "code", "expected", "reason", "field"),
    [
        (403, "ROLE_NOT_PERMITTED", 403, "role_not_permitted", None),
        (409, "DELIVERY_TRANSITION_NOT_ALLOWED", 409, "delivery_transition_not_allowed", None),
        (409, "FULFILLMENT_NOT_READY", 409, "fulfillment_not_ready", None),
        (400, "DELIVERY_DATE_IN_FUTURE", 422, "delivery_date_in_future", "on_date"),
        (400, "DELIVERY_DATE_BEFORE_SHIPPED", 422, "delivery_date_before_shipped", "on_date"),
        (400, "WAYBILL_TOO_LONG", 422, "waybill_too_long", "waybill"),
        (400, "PROOF_INVALID", 422, "proof_invalid", "file"),
    ],
)
async def test_erp_refusals_are_translated(
    web: Web,
    erp: ProjectsFake,
    status: int,
    code: str,
    expected: int,
    reason: str,
    field: str | None,
) -> None:
    await _as(web, "SUPPLY")
    erp.answer("POST", r"projects/\d+/delivery/", erp_error(status, code))
    response = await web.client.post(
        f"{BASE}/{NUMBER}/delivery",
        headers={"X-CSRF-Token": web.csrf},
        **_form(action="delivered", on_date="2026-11-02"),
    )
    assert response.status_code == expected
    body = response.json()
    assert body["details"]["reason"] == reason
    if field:
        assert body["details"]["fields"] == [field]
    if expected != 403:
        assert body["message"] == _ERP_REASONS[code], "текст отказа — словами для сотрудника"


async def test_proof_streams_as_an_attachment_with_the_id_from_the_card(
    web: Web, erp: ProjectsFake, be: Backends
) -> None:
    erp.cards[DEAL] = _delivered_card()
    seen: list[str] = []

    def download(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=PDF, headers={"Content-Type": "text/html"})

    be.router.get(
        url__regex=rf"^{re.escape(ERP_URL)}/api/v1/sourcing/attachments/\d+/download/$"
    ).mock(side_effect=download)
    await _as(web, "MANAGER")
    response = await web.client.get(f"{BASE}/{NUMBER}/delivery/proof")
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert "sandbox" in response.headers["content-security-policy"]
    assert seen == ["/api/v1/sourcing/attachments/77/download/"]


async def test_proof_without_a_file_is_not_found(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "MANAGER")
    response = await web.client.get(f"{BASE}/{NUMBER}/delivery/proof")
    assert response.status_code == 404
