"""docling-serve — конвертация документов в DoclingDocument (SPEC §2, ADR-0011)."""

from typing import Any

import httpx
from docling_core.types.doc import DoclingDocument

from app.config import Settings


class DoclingError(Exception):
    """Конвертация не удалась (статус docling-serve не success)."""


class DoclingDisabledError(DoclingError):
    """docling-serve на этом сервере не используется (`DOCLING_URL` пуст, M5-CRM-02)."""


class DoclingClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        base = settings.docling_url
        self._url = f"{str(base).rstrip('/')}/v1/convert/file" if base is not None else None
        self._headers = {"X-Api-Key": settings.docling_api_key.get_secret_value()}
        self._timeout = settings.docling_timeout_s
        self._http = http

    @property
    def enabled(self) -> bool:
        return self._url is not None

    async def convert(self, filename: str, content: bytes, mime: str) -> DoclingDocument:
        if self._url is None:
            raise DoclingDisabledError("docling is not used on this server (DOCLING_URL is empty)")
        files = {"files": (filename, content, mime)}
        data = {"to_formats": "json"}
        if self._http is not None:
            response = await self._post(self._http, files, data)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await self._post(http, files, data)
        return parse_response(response.json())

    async def _post(self, http: httpx.AsyncClient, files: Any, data: Any) -> httpx.Response:
        assert self._url is not None  # noqa: S101 — проверено в convert()
        response = await http.post(
            self._url, files=files, data=data, headers=self._headers, timeout=self._timeout
        )
        response.raise_for_status()
        return response


def parse_response(payload: dict[str, Any]) -> DoclingDocument:
    status = payload.get("status")
    if status not in {"success", "partial_success"}:
        raise DoclingError(f"docling conversion status={status}: {payload.get('errors')}")
    content = (payload.get("document") or {}).get("json_content")
    if not content:
        raise DoclingError("docling returned no json_content")
    return DoclingDocument.model_validate(content)
