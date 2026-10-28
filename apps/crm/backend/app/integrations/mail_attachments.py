"""Вложения писем других систем — по ссылке на объект их хранилища (W18A-P1, CONTRACTS §9).

ERP и EDS не передают байты вложения по шине: они кладут файл в своё хранилище (ключи S3 у каждого
сервиса свои, S0-9) и передают подписанную ссылку на чтение одного объекта с ограниченным сроком
(внутри зашифрованного `content`). Почтовый воркер CRM скачивает файл перед отправкой — не в пути
пользователя — и сверяет размер и sha256 из события.

Безопасность: ссылка принимается только на хранилище ансамбля (`S3_ENDPOINT`; иначе CRM ходила бы по
любому адресу из события), без перенаправлений, с пределом размера. Итог словами для журнала:
403/404/410 или истёкшая ссылка — `attachment_unavailable` (постоянно); 5xx и сеть — повтор.
"""

import hashlib
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import urlsplit

import httpx

MAX_BYTES: Final = 20 * 1024 * 1024
TIMEOUT_S: Final = 30.0
_GONE: Final = frozenset({400, 401, 403, 404, 410})


class AttachmentError(Exception):
    """Вложение не получено: `reason` — код для журнала, `permanent` — повтор не поможет."""

    def __init__(self, reason: str, detail: str = "", *, permanent: bool) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.permanent = permanent


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    url: str
    filename: str
    content_type: str
    size: int
    sha256: str


class AttachmentFetcher(Protocol):
    async def fetch(self, ref: AttachmentRef) -> bytes: ...


def _origin(url: str) -> str:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{(parts.hostname or '').lower()}:{port}"


class HttpAttachmentFetcher:
    """GET по подписанной ссылке; разрешены только источники `allowed` (схема, хост, порт)."""

    def __init__(
        self,
        allowed: tuple[str, ...],
        *,
        max_bytes: int = MAX_BYTES,
        timeout_s: float = TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allowed = frozenset(_origin(url) for url in allowed if url)
        self._max_bytes = max_bytes
        self._timeout_s = timeout_s
        self._transport = transport

    async def fetch(self, ref: AttachmentRef) -> bytes:
        if _origin(ref.url) not in self._allowed:
            raise AttachmentError("attachment_foreign_host", ref.filename, permanent=True)
        if ref.size > self._max_bytes:
            raise AttachmentError("attachment_too_large", ref.filename, permanent=True)
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout_s, follow_redirects=False, transport=self._transport
                ) as http,
                http.stream("GET", ref.url) as response,
            ):
                if response.status_code in _GONE:
                    raise AttachmentError(
                        "attachment_unavailable",
                        f"{ref.filename}: HTTP {response.status_code}",
                        permanent=True,
                    )
                if response.status_code != 200:
                    raise AttachmentError(
                        "attachment_unavailable",
                        f"{ref.filename}: HTTP {response.status_code}",
                        permanent=False,
                    )
                content = await self._read(response, ref)
        except httpx.HTTPError as exc:
            raise AttachmentError(
                "attachment_unavailable", f"{ref.filename}: {type(exc).__name__}", permanent=False
            ) from exc
        if len(content) != ref.size or hashlib.sha256(content).hexdigest() != ref.sha256:
            raise AttachmentError("attachment_mismatch", ref.filename, permanent=True)
        return content

    async def _read(self, response: httpx.Response, ref: AttachmentRef) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise AttachmentError("attachment_too_large", ref.filename, permanent=True)
            chunks.append(chunk)
        return b"".join(chunks)
