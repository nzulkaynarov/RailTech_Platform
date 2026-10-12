"""Профиль бота в Telegram (имя, описание, краткое описание) — что менять. Чистые функции.

Telegram сильно ограничивает частоту `setMyName` / `setMyDescription`, поэтому публикуем только
отличия от текущих значений (ADR-0018, аудит 2026-10-12 §3 п. 1). Русский — значение по
умолчанию (`language_code` не передаётся), узбекский и английский — по языку клиента Telegram.
"""

from dataclasses import dataclass
from typing import Final, Literal

ProfileField = Literal["name", "description", "short_description"]
FIELDS: Final[tuple[ProfileField, ...]] = ("name", "description", "short_description")
# Лимиты Bot API: setMyName 0–64, setMyDescription 0–512, setMyShortDescription 0–120.
LIMITS: Final[dict[ProfileField, int]] = {"name": 64, "description": 512, "short_description": 120}
LANGUAGE_CODES: Final[tuple[str | None, ...]] = (None, "uz", "en")

Values = dict[tuple[ProfileField, str | None], str]


@dataclass(frozen=True, slots=True)
class ProfileChange:
    field: ProfileField
    language_code: str | None
    value: str


def plan_changes(desired: Values, current: Values) -> list[ProfileChange]:
    """Отличия желаемого профиля от текущего.

    Пустое значение по умолчанию (русское) — не трогаем то, что задано в BotFather.
    Пустое узбекское/английское — убрать отдельный текст языка (Telegram покажет русский);
    если текст языка совпадает с текущим русским, отдельного текста нет — менять нечего.
    """
    changes: list[ProfileChange] = []
    for field in FIELDS:
        current_default = current.get((field, None), "")
        for code in LANGUAGE_CODES:
            wanted = desired.get((field, code), "").strip()
            now = current.get((field, code), "")
            if wanted:
                if wanted != now:
                    changes.append(ProfileChange(field, code, wanted))
            elif code is not None and now != current_default:
                changes.append(ProfileChange(field, code, ""))
    return changes
