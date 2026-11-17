"""Вход в кабинет с нового устройства (ДВ-6; реестр рисков, Д2): сигнал администратору, а не запрет.

Устройство — случайная метка в долгой cookie `PORTAL_DEVICE_COOKIE_NAME` (в базе — только её хеш). Вход по письму (ссылка
или код) с устройства, которого нет у контакта в `PortalKnownDevice`, — событие `login_new_device` в журнале безопасности
компании и уведомление группы `security` её администраторам и основному контакту. Первый вход контакта только запоминает
устройство. Вход через Telegram привязан к аккаунту Telegram — его не проверяем.
"""

from __future__ import annotations

import re
import secrets
from typing import Optional

from django.conf import settings
from django.db.models import Q
from parties.models import Contact, active_contact_q

from ..models import PortalKnownDevice, PortalSecurityEvent, PortalSession, record_portal_security_event
from . import notices
from .tokens import hash_token

_MARK = re.compile(r"^[0-9a-f]{64}$")
DEVICE_COOKIE_MAX_AGE = 400 * 86400  # потолок срока cookie в браузерах


def cookie_name() -> str:
    return getattr(settings, "PORTAL_DEVICE_COOKIE_NAME", "portal_device")


def device_mark(request) -> tuple[str, bool]:
    """Метка устройства из cookie или новая; второй элемент — нужно ли её поставить."""
    raw = request.COOKIES.get(cookie_name(), "")
    if _MARK.match(raw):
        return raw, False
    return secrets.token_hex(32), True


def short_device(user_agent: str) -> str:
    """«Chrome · Windows» из User-Agent — для уведомления, без версий."""
    ua = user_agent or ""
    browser = next(
        (
            name
            for key, name in (
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("YaBrowser", "Яндекс Браузер"),
                ("Chrome/", "Chrome"),
                ("Firefox/", "Firefox"),
                ("Safari/", "Safari"),
            )
            if key in ua
        ),
        "",
    )
    system = next(
        (
            name
            for key, name in (
                ("Android", "Android"),
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Windows", "Windows"),
                ("Mac OS X", "macOS"),
                ("Linux", "Linux"),
            )
            if key in ua
        ),
        "",
    )
    return " · ".join(part for part in (browser, system) if part)


def check(session: PortalSession, mark: str) -> Optional[PortalSecurityEvent]:
    """Запомнить устройство; если у контакта уже есть другие — событие и уведомление администраторам."""
    contact = session.contact
    device_hash = hash_token(mark)
    known = PortalKnownDevice.objects.filter(contact=contact)
    had_devices = known.exists()
    device, created = PortalKnownDevice.objects.get_or_create(contact=contact, device_hash=device_hash)
    if not created:
        device.save(update_fields=["last_seen_at"])
        return None
    if not had_devices:
        return None
    device_name = short_device(session.user_agent)
    event = record_portal_security_event(
        session.company,
        PortalSecurityEvent.EventType.LOGIN_NEW_DEVICE,
        actor_contact=contact,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        details=device_name,
    )
    event.session = session
    event.save(update_fields=["session"])
    recipients = list(
        Contact.objects.filter(
            active_contact_q(), Q(is_admin=True) | Q(is_primary=True), company=session.company
        ).values_list("pk", flat=True)
    )
    notices.notify(
        "new_device_login",
        company=session.company,
        object_id=event.pk,
        params={"name": contact.name, "device": device_name, "ip": session.ip_address or ""},
        link="/company",
        dedup=f"new_device:{event.pk}",
        contact_ids=recipients,
    )
    return event


def end_session(event: PortalSecurityEvent) -> bool:
    """«Это не мы — завершить сеанс»: удалить сеанс события. Уже завершён — False."""
    if event.session_id is None:
        return False
    PortalSession.objects.filter(pk=event.session_id).delete()
    return True
