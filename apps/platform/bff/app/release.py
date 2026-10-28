"""Версия Платформы для «О системе» (W-REL): «Платформа 2026.10.28 · 1a2b3c4».

Версия — по дате выкладки (`PLATFORM_RELEASE_DATE`, её пишет deploy.sh), без неё — по дате
сборки образа (`PLATFORM_BUILD_DATE`, deploy.yml). sha — тег выкладки (`PLATFORM_RELEASE`: все
образы релиза выкладываются одним тегом, полным git sha), без него — sha сборки. Ничего нет —
локальная сборка, версия `dev`.
"""

import re
from datetime import date

from pydantic import BaseModel

from app.config import Settings

_SHA = re.compile(r"^[0-9a-f]{7,40}$")
SHORT_SHA = 7


class Release(BaseModel):
    version: str
    sha: str | None = None
    released_at: date | None = None
    built_at: date | None = None


def _date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip()[:10]) if raw.strip() else None
    except ValueError:
        return None


def is_sha(value: str) -> bool:
    return bool(_SHA.match(value))


def _sha(*candidates: str) -> str | None:
    for raw in candidates:
        value = raw.strip().lower()
        if _SHA.match(value):
            return value[:SHORT_SHA]
    return None


def release_of(settings: Settings) -> Release:
    released = _date(settings.release_date)
    built = _date(settings.build_date)
    day = released or built
    return Release(
        version=day.strftime("%Y.%m.%d") if day else "dev",
        sha=_sha(settings.release, settings.build_sha),
        released_at=released,
        built_at=built,
    )


def release_label(release: Release) -> str:
    """Строка для обращения и поддержки: «Платформа 2026.10.28 · 1a2b3c4»."""
    return " · ".join(part for part in (f"Платформа {release.version}", release.sha) if part)
