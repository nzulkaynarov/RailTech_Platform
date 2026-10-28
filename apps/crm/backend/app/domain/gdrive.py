"""Внешняя копия бэкапов: ключ сервисного аккаунта Google и папка общего диска (OPS-GDRIVE-2).

Чистые функции: разбор JSON-ключа (что это ключ сервисного аккаунта, без чтения лишнего), проверка
ID папки и итог «Проверить» — ответ Google → причина, понятная владельцу. Сетевой обмен —
`app/integrations/gdrive.py`, хранение и доставка — `services/offsite_connector.py`.
"""

import json
import re
from dataclasses import dataclass
from typing import Final, Literal

#: ID папки Drive: буквы, цифры, «_» и «-», обычно 19–44 символа (часть адреса после /folders/).
_FOLDER_ID: Final = re.compile(r"^[A-Za-z0-9_-]{10,128}$")
_FOLDER_URL: Final = re.compile(r"/folders/([A-Za-z0-9_-]{10,128})")
FOLDER_MIME: Final = "application/vnd.google-apps.folder"
#: Ключ сервисного аккаунта — JSON ≈ 2,3 КБ; больше 16 КБ — точно не он.
KEY_MAX_BYTES: Final = 16384

KeyProblem = Literal["not_json", "not_service_account", "missing_fields"]
ProbeReason = Literal[
    "ok",
    "key_rejected",
    "drive_api_disabled",
    "folder_not_found",
    "not_folder",
    "not_shared_drive",
    "read_only",
    "network",
]
#: Что исправлять и кто: всё, кроме сети, — владелец (Google Workspace); сеть — хостинг.
OWNER_REASONS: Final = frozenset(
    {
        "key_rejected",
        "drive_api_disabled",
        "folder_not_found",
        "not_folder",
        "not_shared_drive",
        "read_only",
    }
)


@dataclass(frozen=True, slots=True)
class ServiceAccountKey:
    """Нужное из JSON-ключа: адрес аккаунта (виден админу), ID ключа (последние символы — маска),
    закрытый ключ (только для подписи запроса к Google, наружу не отдаётся)."""

    client_email: str
    private_key_id: str
    private_key: str
    token_uri: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    reason: ProbeReason
    folder_name: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


def parse_key(raw: str) -> ServiceAccountKey | KeyProblem:
    """JSON ключа сервисного аккаунта → поля; иначе — что не так (без значений в тексте)."""
    if len(raw.encode()) > KEY_MAX_BYTES:
        return "not_json"
    try:
        data = json.loads(raw)
    except ValueError:
        return "not_json"
    if not isinstance(data, dict):
        return "not_json"
    if data.get("type") != "service_account":
        return "not_service_account"
    fields = ("client_email", "private_key_id", "private_key")
    values = [data.get(f) for f in fields]
    if not all(isinstance(v, str) and v for v in values):
        return "missing_fields"
    email, key_id, private_key = (str(v) for v in values)
    if "@" not in email or "PRIVATE KEY" not in private_key:
        return "missing_fields"
    token_uri = data.get("token_uri")
    return ServiceAccountKey(
        client_email=email,
        private_key_id=key_id,
        private_key=private_key,
        token_uri=token_uri
        if isinstance(token_uri, str) and token_uri.startswith("https://")
        else "https://oauth2.googleapis.com/token",
    )


def key_suffix(key_id: str) -> str:
    """Маска ключа для экрана: последние 4 символа ID ключа (не закрытого ключа)."""
    return key_id[-4:] if len(key_id) >= 8 else "****"


def normalize_folder_id(value: str) -> str | None:
    """ID папки из поля: сам ID или вставленный адрес папки (`…/folders/<ID>?usp=…`); иначе None."""
    text = value.strip()
    if (match := _FOLDER_URL.search(text)) is not None:
        return match.group(1)
    return text if _FOLDER_ID.fullmatch(text) else None


def classify_token_error(status: int, body: object) -> ProbeResult:
    """Ответ `oauth2.googleapis.com/token` не 200: ключ отозван, удалён, аккаунт выключен."""
    error = body.get("error") if isinstance(body, dict) else None
    if status >= 500:
        return ProbeResult("network", detail=f"token endpoint {status}")
    return ProbeResult("key_rejected", detail=str(error or status))


def classify_folder(status: int, body: object) -> ProbeResult:
    """Ответ `drive/v3/files/<папка>`: есть ли папка, на общем ли диске, можно ли писать."""
    if status == 200 and isinstance(body, dict):
        name = body.get("name") if isinstance(body.get("name"), str) else None
        if body.get("mimeType") != FOLDER_MIME:
            return ProbeResult("not_folder", name)
        if not body.get("driveId"):
            return ProbeResult("not_shared_drive", name)
        caps = body.get("capabilities")
        if not (isinstance(caps, dict) and caps.get("canAddChildren") is True):
            return ProbeResult("read_only", name)
        return ProbeResult("ok", name)
    reason = _google_reason(body)
    if status == 404:
        return ProbeResult("folder_not_found", detail=reason)
    if status == 403 and reason in ("accessNotConfigured", "SERVICE_DISABLED"):
        return ProbeResult("drive_api_disabled", detail=reason)
    if status in (401, 403) and reason not in ("rateLimitExceeded", "userRateLimitExceeded"):
        return ProbeResult("key_rejected", detail=reason or str(status))
    return ProbeResult("network", detail=reason or str(status))


def _google_reason(body: object) -> str | None:
    """`error.errors[0].reason` или `error.details[].reason` из ответа Google API."""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    for item in error.get("errors") or []:
        if isinstance(item, dict) and isinstance(item.get("reason"), str):
            return str(item["reason"])
    for item in error.get("details") or []:
        if isinstance(item, dict) and isinstance(item.get("reason"), str):
            return str(item["reason"])
    status = error.get("status")
    return status if isinstance(status, str) else None
