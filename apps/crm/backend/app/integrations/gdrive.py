"""«Проверить» внешней копии (OPS-GDRIVE-2): ключ сервисного аккаунта → токен Google → папка Drive.

Без SDK Google: подписанный ключом аккаунта JWT (RS256) меняется на токен доступа
(`oauth2.googleapis.com/token`, область `drive.readonly`), затем `GET drive/v3/files/<папка>` —
есть ли папка, на общем ли диске, может ли аккаунт добавлять в неё файлы. Ничего не пишет на Drive.
Закрытый ключ из памяти никуда не уходит: только подпись запроса.
"""

import asyncio
import time

import httpx
import jwt

from app.domain.gdrive import (
    TOKEN_URI,
    ProbeResult,
    ServiceAccountKey,
    classify_folder,
    classify_token_error,
)

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
TIMEOUT_S = 15.0
TOTAL_S = 20.0


def assertion(key: ServiceAccountKey, now: float | None = None) -> str:
    """JWT-утверждение сервисного аккаунта для обмена на токен (RFC 7523), живёт 10 минут."""
    issued = int(now if now is not None else time.time())
    claims = {
        "iss": key.client_email,
        "scope": SCOPE,
        "aud": TOKEN_URI,
        "iat": issued,
        "exp": issued + 600,
    }
    return jwt.encode(
        claims, key.private_key, algorithm="RS256", headers={"kid": key.private_key_id}
    )


async def probe(
    key: ServiceAccountKey,
    folder_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProbeResult:
    """Вся проверка — не дольше `TOTAL_S`: BFF ждёт ответа пробы до 30 с."""
    try:
        async with asyncio.timeout(TOTAL_S):
            return await _probe(key, folder_id, transport)
    except TimeoutError:
        return ProbeResult("network", detail="timeout")


async def _probe(
    key: ServiceAccountKey, folder_id: str, transport: httpx.AsyncBaseTransport | None
) -> ProbeResult:
    try:
        signed = assertion(key)
    except (ValueError, TypeError, jwt.PyJWTError):
        return ProbeResult("key_rejected", detail="private_key_unreadable")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as http:
            token = await http.post(
                TOKEN_URI,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed,
                },
            )
            if token.status_code != 200:
                return classify_token_error(token.status_code, _json(token))
            body = _json(token)
            access = body.get("access_token") if isinstance(body, dict) else None
            if not isinstance(access, str):
                return ProbeResult("key_rejected", detail="no_access_token")
            folder = await http.get(
                f"{DRIVE_FILES}/{folder_id}",
                params={
                    "supportsAllDrives": "true",
                    "fields": "id,name,mimeType,driveId,capabilities/canAddChildren",
                },
                headers={"Authorization": f"Bearer {access}"},
            )
            return classify_folder(folder.status_code, _json(folder))
    except httpx.HTTPError as exc:
        return ProbeResult("network", detail=type(exc).__name__)


def _json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None
