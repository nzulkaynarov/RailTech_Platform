"""Бланк своей компании → EDS: событие `uz.railtech.erp.letterhead.updated.v1` (P4 волны 18a; ADR-0020 п. 5).

ERP — владелец реквизитов. Админ сохраняет «Компания и бланки» (реквизиты или логотип документов) — сервис профиля
публикует снимок бланка целиком в той же транзакции (outbox rt_bus): EDS держит проекцию для писем на бланке. Только своя
компания ERP (`core.tenant.own_company_id`): профили других компаний EDS не нужны.

Логотип — байтами (PNG, JPEG или WebP ≤ 512 КиБ, как `rt_docs.Logo`): большой растр уменьшается до размера шапки
бланка (Pillow), SVG и непрочитанный файл — `logo = null`, `logo_omitted = unsupported`; «Показывать логотип» выключено —
`hidden`. Схема — `packages/contracts/events/erp/letterhead.updated.v1.json`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from typing import Any, Dict, Optional, Tuple

from django.db import transaction

logger = logging.getLogger(__name__)

LETTERHEAD_UPDATED = "uz.railtech.erp.letterhead.updated.v1"
LOGO_MAX_BYTES = 512 * 1024
LOGO_BOX = (1200, 400)  # шапка бланка — логотип не шире 1200 и не выше 400 px
_PIL_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def _logo(profile) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Логотип для события: (`logo`, `logo_omitted`)."""
    if not profile.logo:
        return None, None
    if not profile.show_logo:
        return None, "hidden"
    try:
        profile.logo.open("rb")
        try:
            raw = profile.logo.read()
        finally:
            profile.logo.close()
        data, content_type = _fit(raw)
    except Exception:  # noqa: BLE001 — непрочитанный файл логотипа не должен ломать сохранение реквизитов
        logger.info("letterhead logo is not a raster image", exc_info=True)
        return None, "unsupported"
    if data is None:
        return None, "too_large"
    return (
        {
            "content_type": content_type,
            "data_base64": base64.b64encode(data).decode("ascii"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        },
        None,
    )


def _fit(raw: bytes) -> Tuple[Optional[bytes], str]:
    """Растр как есть, если подходит; иначе — уменьшенный PNG (с прозрачностью) или JPEG. SVG — исключение Pillow."""
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        kind = _PIL_TYPES.get(image.format or "")
        if kind and len(raw) <= LOGO_MAX_BYTES and image.width <= LOGO_BOX[0] and image.height <= LOGO_BOX[1]:
            return raw, kind
        picture = image.convert("RGBA") if image.mode not in ("RGB", "RGBA") else image.copy()
    picture.thumbnail(LOGO_BOX)
    out = io.BytesIO()
    picture.save(out, format="PNG", optimize=True)
    if out.tell() <= LOGO_MAX_BYTES:
        return out.getvalue(), "image/png"
    out = io.BytesIO()
    picture.convert("RGB").save(out, format="JPEG", quality=85)
    return (out.getvalue() if out.tell() <= LOGO_MAX_BYTES else None), "image/jpeg"


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def letterhead_data(company, profile, user=None) -> Dict[str, Any]:
    """`data` события по профилю документов компании."""
    from integration.services.event_builders import build_actor

    logo, omitted = _logo(profile)
    accent = _text(profile.accent_color, 7)
    head: Dict[str, Any] = {
        "company_name": _text(profile.legal_name or company.name, 255),
        "inn": _text(profile.inn, 20),
        "legal_address": _text(profile.legal_address, 2000),
        "bank_details": _text(profile.bank_details, 2000),
        "signatory_name": _text(profile.signatory_name, 255),
        "signatory_position": _text(profile.signatory_position, 255),
        "footer_text": _text(profile.footer_text, 2000),
        "accent_color": accent if len(accent) == 7 else "",
        "font_family": profile.font_family if profile.font_family in ("sans", "serif") else "sans",
        "logo": logo,
    }
    if omitted:
        head["logo_omitted"] = omitted
    return {"erp_company_id": int(company.id), "actor": build_actor(user), "letterhead": head}


def publish_letterhead(company, profile, user=None):
    """Снимок бланка в outbox текущей транзакции — только для своей компании ERP; иначе `None`."""
    from integration.bus import get_bus

    from core.tenant import own_company_id

    if own_company_id() != company.id:
        return None
    data = letterhead_data(company, profile, user)
    with transaction.atomic():
        return get_bus().publish(LETTERHEAD_UPDATED, data, subject=f"company/{int(company.id)}")
