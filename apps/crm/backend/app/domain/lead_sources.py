"""Источники лидов и склейка по номеру телефона (ARCHITECTURE §17, M3-CRM-05). Чистые функции.

Лид приходит не только из Telegram: форма «Запрос» на сайте (`web`) и ручное создание
менеджером (`phone` — звонок, `email`, `referral`). Жизненный цикл один и тот же. Лид с номером,
который позже написал в бот и поделился тем же номером, **склеивается** с существующим: одна
карточка, Telegram-идентичность добавляется, история сохраняется, стадия не понижается,
источник — первый.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from app.domain.bot_menu import normalize_phone
from app.domain.stages import OwnerMode, Stage

# Пометка заметки с повторным запросом с сайта (текст запроса — после неё).
WEB_NOTE_MARK: Final = "[web] "


class LeadSource(StrEnum):
    TELEGRAM = "telegram"
    WEB = "web"
    PHONE = "phone"
    EMAIL = "email"
    REFERRAL = "referral"


# Источники, которые выбирает менеджер в форме «Новый лид».
MANUAL_SOURCES: Final[frozenset[LeadSource]] = frozenset(
    {LeadSource.PHONE, LeadSource.EMAIL, LeadSource.REFERRAL}
)

_UZ_COUNTRY: Final = "998"
_UZ_LOCAL_LEN: Final = 9
_INTL_MIN_AFTER_00: Final = 10
_UZ_FULL_LEN: Final = len(_UZ_COUNTRY) + _UZ_LOCAL_LEN
_DIGITS: Final = re.compile(r"\D", re.ASCII)
_PHONE_CHARS: Final = re.compile(r"\+?[\d\s()\-.]+", re.ASCII)


def normalize_phone_e164(raw: str | None) -> str | None:
    """Номер из формы → E.164; узбекские номера без кода страны получают `+998`.

    Принимает `+998 90 123-45-67`, `998901234567`, `00998…`, `90 123 45 67` (9 цифр — местный
    формат Узбекистана) и любой международный номер с кодом. Номер Узбекистана — ровно `+998`
    и 9 цифр; «8 90 123 45 67» (местный префикс 8), короткие и слишком длинные → None.
    """
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if not _PHONE_CHARS.fullmatch(text):
        return None
    digits = _DIGITS.sub("", text)
    international = text.startswith("+")
    if not international:
        if digits.startswith("00"):
            # «00» is the international prefix only before a country code and a real number.
            digits = digits[2:]
            if len(digits) < _INTL_MIN_AFTER_00:
                return None
        elif len(digits) == _UZ_LOCAL_LEN:
            digits = _UZ_COUNTRY + digits
        elif digits.startswith("8") and len(digits) == _UZ_LOCAL_LEN + 1:
            return None
    if digits.startswith(_UZ_COUNTRY) and len(digits) != _UZ_FULL_LEN:
        return None
    return normalize_phone(f"+{digits}")


# «Не понижать стадию» при склейке: выше ранг — дальше по воронке.
STAGE_RANK: Final[dict[Stage, int]] = {
    Stage.NEW: 0,
    Stage.UNRESPONSIVE: 0,
    Stage.LOST: 1,
    Stage.ENGAGED: 2,
    Stage.QUALIFIED: 3,
    Stage.HANDOFF: 4,
    Stage.IN_PROGRESS: 5,
    Stage.WON: 6,
    Stage.CUSTOMER: 7,
}
_OWNER_RANK: Final[dict[str, int]] = {
    OwnerMode.BOT.value: 0,
    OwnerMode.PAUSED.value: 1,
    OwnerMode.HUMAN.value: 2,
}


@dataclass(frozen=True, slots=True)
class LeadFacts:
    """Снимок лида для правила склейки (без I/O)."""

    id: int
    created_at: datetime
    source: str
    stage: str
    score: int = 0
    owner_mode: str = OwnerMode.BOT.value
    assigned_user_id: int | None = None
    language: str = "ru"
    language_confirmed: bool = False
    display_name: str = ""
    need_summary: str | None = None
    consent_given_at: datetime | None = None
    product_interest: tuple[str, ...] = ()
    qualification: dict[str, Any] = field(default_factory=dict)
    company_name: str | None = None
    email: str | None = None
    phone_e164: str | None = None
    client_id: int | None = None
    has_open_escalation: bool = False
    # Origin facts (LID-5) and consent version/method; the merge fills the empty ones.
    source_form: str | None = None
    source_page: str | None = None
    source_referrer: str | None = None
    source_utm: dict[str, str] | None = None
    source_lang: str | None = None
    consent_version: str | None = None
    consent_method: str | None = None


@dataclass(frozen=True, slots=True)
class MergePlan:
    """Что сделать с двумя карточками: кто остаётся и какие поля у него будут."""

    survivor_id: int
    absorbed_id: int
    source: str
    stage: Stage
    stage_changed: bool
    score: int
    owner_mode: str
    assigned_user_id: int | None
    language: str
    language_confirmed: bool
    display_name: str
    need_summary: str | None
    consent_given_at: datetime | None
    product_interest: tuple[str, ...]
    qualification: dict[str, Any]
    company_name: str | None
    email: str | None
    phone_e164: str | None
    client_id: int | None
    # У обоих открытая передача: у поглощённого закрывается (индекс «одна открытая на лида»).
    close_absorbed_escalation: bool
    source_form: str | None = None
    source_page: str | None = None
    source_referrer: str | None = None
    source_utm: dict[str, str] | None = None
    source_lang: str | None = None
    consent_version: str | None = None
    consent_method: str | None = None
    # Origin of the absorbed card when it differs from the survivor's: kept as a fact, not lost.
    absorbed_origin: dict[str, Any] | None = None


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value
    return None


def _union(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for item in (*a, *b):
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def _earliest(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _origin(f: LeadFacts) -> dict[str, Any]:
    facts = {
        "form": f.source_form,
        "page": f.source_page,
        "referrer": f.source_referrer,
        "utm": f.source_utm,
        "landing_language": f.source_lang,
    }
    return {k: v for k, v in facts.items() if v}


def merge_plan(existing: LeadFacts, incoming: LeadFacts) -> MergePlan:
    """Правило склейки двух лидов с одним номером.

    - Остаётся **более ранняя** карточка (`created_at`, затем `id`): источник — первый.
    - Стадия — дальняя по воронке (`STAGE_RANK`), не понижается ни у одного.
    - Ведущий: менеджер важнее паузы, пауза важнее бота; ответственный — у кого он есть
      (у выжившего приоритет).
    - Оценка — максимум; согласие — самое раннее; интересы — объединение;
      квалификация — поля поглощённого дополняют, не перезаписывают.
    - Язык — подтверждённый выбор важнее определённого автоматически.
    - Имя, потребность, компания, почта, телефон — у выжившего, если заполнены, иначе у второго.
    """
    first, second = sorted((existing, incoming), key=lambda f: (f.created_at, f.id))
    origin_donor = first if _origin(first) else second
    consenting = [f for f in (first, second) if f.consent_given_at is not None]
    consent_donor = (
        min(consenting, key=lambda f: f.consent_given_at or first.created_at)
        if consenting
        else None
    )
    absorbed_origin = (
        _origin(second)
        if _origin(first) and _origin(second) and _origin(first) != _origin(second)
        else None
    )
    stages = (Stage(first.stage), Stage(second.stage))
    stage = max(stages, key=lambda s: STAGE_RANK[s])
    owner_mode = max((first.owner_mode, second.owner_mode), key=lambda m: _OWNER_RANK.get(m, 0))
    assigned = first.assigned_user_id if first.assigned_user_id is not None else None
    if assigned is None:
        assigned = second.assigned_user_id
    if first.language_confirmed or not second.language_confirmed:
        language, confirmed = first.language, first.language_confirmed
    else:
        language, confirmed = second.language, True
    return MergePlan(
        survivor_id=first.id,
        absorbed_id=second.id,
        source=first.source,
        stage=stage,
        stage_changed=stage != stages[0],
        score=max(first.score, second.score),
        owner_mode=owner_mode,
        assigned_user_id=assigned,
        language=language,
        language_confirmed=confirmed,
        display_name=_first_nonempty(first.display_name, second.display_name) or "",
        need_summary=_first_nonempty(first.need_summary, second.need_summary),
        consent_given_at=_earliest(first.consent_given_at, second.consent_given_at),
        product_interest=_union(first.product_interest, second.product_interest),
        qualification={**second.qualification, **first.qualification},
        company_name=_first_nonempty(first.company_name, second.company_name),
        email=_first_nonempty(first.email, second.email),
        phone_e164=_first_nonempty(first.phone_e164, second.phone_e164),
        client_id=first.client_id if first.client_id is not None else second.client_id,
        close_absorbed_escalation=first.has_open_escalation and second.has_open_escalation,
        source_form=origin_donor.source_form,
        source_page=origin_donor.source_page,
        source_referrer=origin_donor.source_referrer,
        source_utm=origin_donor.source_utm,
        source_lang=origin_donor.source_lang,
        consent_version=consent_donor.consent_version if consent_donor else None,
        consent_method=consent_donor.consent_method if consent_donor else None,
        absorbed_origin=absorbed_origin,
    )
