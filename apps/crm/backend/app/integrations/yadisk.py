"""«Проверить» внешней копии на Яндекс Диске (OPS-YADISK): WebDAV логином и паролем приложения.

1. `PROPFIND /` — вход принят (401 — логин или пароль, 403 — WebDAV закрыт администратором 360);
2. папка: есть — должна быть папкой; нет — создаётся по цепочке `MKCOL`;
3. запись и удаление маленького проверочного файла — сервис копирования сможет писать и чистить срок
   хранения (507 — нет места).
Пароль уходит только заголовком Basic на `webdav.yandex.ru` по HTTPS и нигде не печатается.
"""

import asyncio
import secrets
from urllib.parse import quote

import httpx

from app.domain.yadisk import WEBDAV_URL, ProbeResult, classify_status, is_collection

TIMEOUT_S = 15.0
TOTAL_S = 20.0
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
)


def _href(parts: list[str]) -> str:
    return "/" + "/".join(quote(p, safe="") for p in parts)


async def probe(
    login: str,
    password: str,
    folder: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = WEBDAV_URL,
) -> ProbeResult:
    """Вся проверка — не дольше `TOTAL_S`: BFF ждёт ответа пробы до 30 с."""
    try:
        async with asyncio.timeout(TOTAL_S):
            return await _probe(login, password, folder, transport, base_url)
    except TimeoutError:
        return ProbeResult("network", detail="timeout")


async def _probe(
    login: str,
    password: str,
    folder: str,
    transport: httpx.AsyncBaseTransport | None,
    base_url: str,
) -> ProbeResult:
    parts = [p for p in folder.split("/") if p]
    headers = {"Depth": "0", "Content-Type": "application/xml; charset=utf-8"}
    try:
        async with httpx.AsyncClient(
            base_url=base_url, auth=(login, password), timeout=TIMEOUT_S, transport=transport
        ) as http:
            root = await http.request("PROPFIND", "/", headers=headers, content=_PROPFIND_BODY)
            if (problem := classify_status(root.status_code, password)) is not None:
                return problem
            found = await http.request(
                "PROPFIND", _href(parts), headers=headers, content=_PROPFIND_BODY
            )
            if found.status_code == 404:
                for depth in range(1, len(parts) + 1):
                    made = await http.request("MKCOL", _href(parts[:depth]))
                    # 405 — уже есть (часть пути создана раньше); 201 — создана.
                    if made.status_code != 405 and (
                        problem := classify_status(made.status_code, password)
                    ):
                        return problem
            elif (problem := classify_status(found.status_code, password)) is not None:
                return problem
            elif not is_collection(found.text):
                return ProbeResult("not_folder", folder)
            probe_file = _href([*parts, f".rt-offsite-check-{secrets.token_hex(4)}.txt"])
            put = await http.put(probe_file, content=b"RailTech offsite check\n")
            if (problem := classify_status(put.status_code, password)) is not None:
                return problem
            gone = await http.delete(probe_file)
            if gone.status_code != 404 and (problem := classify_status(gone.status_code, password)):
                return problem
            return ProbeResult("ok", folder)
    except httpx.HTTPError as exc:
        return ProbeResult("network", detail=type(exc).__name__)
