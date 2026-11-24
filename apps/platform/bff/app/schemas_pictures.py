"""Адреса логотипа компании и фото контакта (ЕД-5, СУЩ-3).

Только через BFF; версия в адресе сбрасывает кэш браузера. ERP отдаёт версию (`logo_version`,
`photo_version`), а не адрес хранилища; без версии картинки нет, клиент показывает буквы названия
или инициалы.
"""

from typing import Any

COMPANY_LOGO_PATH = "/api/v1/people/counterparties/{id}/logo"
CONTACT_PHOTO_PATH = "/api/v1/people/contacts/{id}/photo"


def _url(path: str, ident: Any, version: Any) -> str | None:
    if ident in (None, "") or not isinstance(version, str) or not version:
        return None
    return f"{path.format(id=ident)}?v={version}"


def company_logo_url(company_id: Any, version: Any) -> str | None:
    return _url(COMPANY_LOGO_PATH, company_id, version)


def contact_photo_url(contact_id: Any, version: Any) -> str | None:
    return _url(CONTACT_PHOTO_PATH, contact_id, version)
