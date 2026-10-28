"""Ссылки уведомлений CRM: Платформа вместо старой CRM (W15-H8b, B-009).

Единственная карта «что открыть → маршрут». Каждое уведомление (Telegram лиду и менеджеру, канал
команды, итоги дня, оповещения «Внешних сервисов») берёт адрес отсюда, поэтому новый маршрут
добавляется в одном месте.

Платформа — `PLATFORM_PUBLIC_URL` (или `PLATFORM_DOMAIN`). Маршрут объекта без настоящего экрана
ведёт на раздел Платформы, где работает мост («Открыть в …» в старую систему); когда экран появится
(волна 16), маршрут тот же, и ссылки в уже отправленных сообщениях не ломаются. Адреса Платформы
нет — прежняя ссылка в старую CRM (`company.crm_base_url`), а «Состояние системы» предупреждает в
строке «Адреса для ссылок». У объектов, которых в старой CRM не было («Подключения», журнал
обмена), запасной ссылки нет — `None`, сообщение уходит без ссылки.

Чистые функции, сети и настроек не касаются.
"""

from dataclasses import dataclass
from typing import Final, Literal, cast

LinkKind = Literal["lead", "dashboard", "integrations", "bus"]

#: Платформа: номер лида — как в её очереди и поиске (`L-0042`), боковое окно с карточкой.
_PLATFORM: Final[dict[str, str]] = {
    "lead": "/crm/leads?lead=L-{ref:04d}&panel=open&tab=card",
    "dashboard": "/dashboard/summary",
    "integrations": "/admin/integrations",
    "bus": "/admin/bus",
}
#: Старая CRM (запасной вариант без адреса Платформы).
_LEGACY: Final[dict[str, str | None]] = {
    "lead": "/leads/{ref}",
    "dashboard": "/dashboard",
    "integrations": None,
    "bus": None,
}


def notification_link(
    kind: LinkKind, ref: int | None, *, platform: str | None, crm: str
) -> str | None:
    """Адрес объекта: Платформа, если её адрес известен, иначе старая CRM; None — ссылки нет."""
    if kind not in _PLATFORM:
        raise ValueError(f"unknown link kind: {kind!r}")
    if kind == "lead" and ref is None:
        raise ValueError("link kind 'lead' needs a lead id")
    root = (platform or "").strip().rstrip("/")
    if root:
        return root + _PLATFORM[kind].format(ref=ref)
    legacy = _LEGACY[kind]
    return None if legacy is None else crm.strip().rstrip("/") + legacy.format(ref=ref)


@dataclass(frozen=True, slots=True)
class LinkBase:
    """Адреса, от которых строятся ссылки: Платформа (из окружения) и старая CRM (из «Настроек»)."""

    platform: str | None
    crm: str

    @property
    def on_platform(self) -> bool:
        return bool((self.platform or "").strip())

    def lead(self, lead_id: int) -> str:
        # у лида есть и маршрут Платформы, и старый адрес: None невозможен
        return cast(str, notification_link("lead", lead_id, platform=self.platform, crm=self.crm))

    def dashboard(self) -> str:
        return cast(str, notification_link("dashboard", None, platform=self.platform, crm=self.crm))

    def integrations(self) -> str | None:
        return notification_link("integrations", None, platform=self.platform, crm=self.crm)
