"""Внешняя копия бэкапов на Яндекс Диске компании (OPS-YADISK, решение владельца 2026-10-31).

Подключение — WebDAV (`webdav.yandex.ru`) логином Яндекс 360 и паролем приложения типа «Файлы».
Чистые функции: проверка логина и пути папки, вид пароля приложения и итог «Проверить» — ответ
WebDAV → причина, понятная владельцу. Сетевой обмен — `app/integrations/yadisk.py`, хранение и
доставка — `services/offsite_connector.py`.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

WEBDAV_URL: Final = "https://webdav.yandex.ru"
#: Папка по умолчанию: `RailTech-backups/<окружение>` — копии разных окружений не смешиваются.
FOLDER_ROOT: Final = "RailTech-backups"
FOLDER_MAX: Final = 255
LOGIN_MAX: Final = 254
PASSWORD_MAX: Final = 256
#: Адрес почты: буквы (в том числе кириллица), цифры, «.», «_», «%», «+», «-». Без «#», кавычек и
#: обратной косой — логин уходит в settings.json, а сервис копирования скрывает его в журнале через
# sed.
_LOGIN: Final = re.compile(r"^[\w.%+-]+@[\w-]+(?:\.[\w-]+)+$")
#: Часть пути: буквы (в том числе кириллица), цифры, пробел, «_», «-», «.», скобки. Без кавычек и
#: обратной косой — путь уходит в settings.json и в rclone через sh.
_SEGMENT: Final = re.compile(r"^[\w .()-]{1,100}$")
#: Пароль приложения Яндекса — 16 строчных латинских букв; иное — скорее обычный пароль аккаунта.
_APP_PASSWORD: Final = re.compile(r"^[a-z]{16}$")

ProbeReason = Literal[
    "ok",
    "auth_failed",
    "not_app_password",
    "webdav_forbidden",
    "not_folder",
    "no_space",
    "network",
]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    reason: ProbeReason
    folder_name: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


def default_folder(env: str) -> str:
    return f"{FOLDER_ROOT}/{env}"


def normalize_login(value: str) -> str | None:
    """Адрес почты Яндекс 360 (логин WebDAV) в нижнем регистре; не адрес — None."""
    text = value.strip().lower()
    return text if len(text) <= LOGIN_MAX and _LOGIN.fullmatch(text) else None


def normalize_folder(value: str) -> str | None:
    """Путь папки на Диске без крайних «/» и пустых частей; «.», «..» и лишние знаки — None."""
    text = value.strip().replace("\\", "/")
    if text.startswith("disk:"):
        text = text[len("disk:") :]
    parts = [p.strip() for p in text.split("/") if p.strip()]
    if not parts or any(p in (".", "..") or not _SEGMENT.fullmatch(p) for p in parts):
        return None
    path = "/".join(parts)
    return path if len(path) <= FOLDER_MAX else None


def normalize_password(value: str) -> str:
    """Пароль приложения без пробелов: при копировании его иногда разбивают на группы."""
    return "".join(value.split())


def looks_like_app_password(value: str) -> bool:
    return _APP_PASSWORD.fullmatch(value) is not None


def classify_status(status: int, password: str) -> ProbeResult | None:
    """Ответ WebDAV не «успех» → причина; успех (2xx, 207) — None.

    401 — логин или пароль не приняты: если пароль не похож на пароль приложения, скорее всего
    введён
    обычный пароль аккаунта; 403 — WebDAV запрещён (администратор Яндекс 360 закрыл доступ к Диску
    по протоколу или у аккаунта нет Диска); 507 — нет места; 5xx, 429 и прочее — связь (хостинг).
    """
    if 200 <= status < 300:
        return None
    if status == 401:
        reason: ProbeReason = (
            "auth_failed" if looks_like_app_password(password) else "not_app_password"
        )
        return ProbeResult(reason, detail="401")
    if status == 403:
        return ProbeResult("webdav_forbidden", detail="403")
    if status == 507:
        return ProbeResult("no_space", detail="507")
    return ProbeResult("network", detail=str(status))


_COLLECTION: Final = re.compile(r"<[^>]*resourcetype[^>]*>\s*<[^>]*collection", re.IGNORECASE)


def is_collection(body: str) -> bool:
    """Ответ PROPFIND (Depth: 0): ресурс — папка (`<d:resourcetype><d:collection/>`)."""
    return _COLLECTION.search(body) is not None
