"""Реестр зон ответственности в CRM (`/api/v1/responsibility-zones`, ЕВ-З).

Вызовы идут от имени сотрудника через `Authed.call`. Право, проверки людей и разделов и журнал —
в CRM; здесь только перевод ошибок в формат `Error` контракта (`crm_error`)."""

from typing import Any

from app.clients.crm_users import Call, crm_error

ZONES = "/api/v1/responsibility-zones"


class CrmZones:
    def __init__(self, call: Call) -> None:
        self._call = call

    async def _json(self, method: str, path: str, expected: int, *, json: Any = None) -> Any:
        response = await self._call("crm", method, path, json=json)
        if response.status_code != expected:
            raise crm_error(response)
        return response.json() if response.content else None

    async def list_all(self) -> list[dict[str, Any]]:
        payload = await self._json("GET", ZONES, 200)
        items: list[dict[str, Any]] = payload["items"]
        return items

    async def summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = await self._json("GET", f"{ZONES}/summary", 200)
        return summary

    async def get(self, zone_id: str) -> dict[str, Any]:
        zone: dict[str, Any] = await self._json("GET", f"{ZONES}/{zone_id}", 200)
        return zone

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        zone: dict[str, Any] = await self._json("POST", ZONES, 201, json=payload)
        return zone

    async def update(self, zone_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        zone: dict[str, Any] = await self._json("PATCH", f"{ZONES}/{zone_id}", 200, json=payload)
        return zone

    async def set_active(self, zone_id: str, active: bool) -> dict[str, Any]:
        action = "activate" if active else "deactivate"
        zone: dict[str, Any] = await self._json("POST", f"{ZONES}/{zone_id}/{action}", 200)
        return zone
