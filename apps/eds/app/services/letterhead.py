"""Бланк компании — проекция события ERP `uz.railtech.erp.letterhead.updated.v1` (P4; ADR-0020 п. 5).

ERP — владелец реквизитов своей компании; админ правит их в Платформе (Настройки · Компания и бланки), ERP публикует
снимок
целиком. EDS держит одну строку `letterhead` и логотипы по SHA-256; более старый снимок (по `time` события) не
применяется.
"""

import base64
import binascii
import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.models import Letterhead, LetterheadLogo

LOGO_MAX_BYTES = 512 * 1024
_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LogoIn(_Tolerant):
    content_type: str
    data_base64: str
    sha256: str
    size: int


class LetterheadIn(_Tolerant):
    company_name: str = ""
    inn: str = ""
    legal_address: str = ""
    bank_details: str = ""
    signatory_name: str = ""
    signatory_position: str = ""
    footer_text: str = ""
    accent_color: str = ""
    font_family: str = "sans"
    logo: LogoIn | None = None
    logo_omitted: str | None = None


class LetterheadUpdated(_Tolerant):
    erp_company_id: int
    letterhead: LetterheadIn = Field(default_factory=LetterheadIn)


class LogoError(ValueError):
    """Логотип события не совпадает с хешем, размером или сигнатурой типа."""


def _logo_bytes(logo: LogoIn) -> bytes:
    try:
        data = base64.b64decode(logo.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LogoError("logo is not base64") from exc
    if not data or len(data) > LOGO_MAX_BYTES or len(data) != logo.size:
        raise LogoError("logo size mismatch")
    if hashlib.sha256(data).hexdigest() != logo.sha256:
        raise LogoError("logo sha256 mismatch")
    if not data.startswith(_SIGNATURES.get(logo.content_type, (b"\x00\x00",))):
        raise LogoError("logo signature mismatch")
    if logo.content_type == "image/webp" and data[8:12] != b"WEBP":
        raise LogoError("logo signature mismatch")
    return data


async def apply(session: AsyncSession, data: LetterheadUpdated, *, moment: datetime) -> bool:
    """Применить снимок бланка; `False` — у проекции снимок новее (повтор или опоздавшее событие)."""
    current = await session.get(Letterhead, 1, with_for_update=True)
    if current is not None and current.source_time >= moment:
        return False
    src = data.letterhead
    logo_sha: str | None = None
    if src.logo is not None:
        raw = _logo_bytes(src.logo)
        logo_sha = src.logo.sha256
        if await session.get(LetterheadLogo, logo_sha) is None:
            session.add(
                LetterheadLogo(sha256=logo_sha, content_type=src.logo.content_type, data=raw, created_at=clock.now())
            )
            await session.flush()
    accent = src.accent_color if len(src.accent_color) == 7 else ""
    values: dict[str, Any] = {
        "erp_company_id": data.erp_company_id,
        "company_name": src.company_name[:255],
        "inn": src.inn[:20],
        "legal_address": src.legal_address,
        "bank_details": src.bank_details,
        "signatory_name": src.signatory_name[:255],
        "signatory_position": src.signatory_position[:255],
        "footer_text": src.footer_text,
        "accent_color": accent,
        "font_family": src.font_family if src.font_family in ("sans", "serif") else "sans",
        "logo_sha256": logo_sha,
        "logo_omitted": src.logo_omitted,
        "source_time": moment,
        "updated_at": clock.now(),
    }
    if current is None:
        session.add(Letterhead(id=1, **values))
    else:
        for key, value in values.items():
            setattr(current, key, value)
    await session.flush()
    return True


async def current(session: AsyncSession) -> Letterhead | None:
    return (await session.execute(select(Letterhead).where(Letterhead.id == 1))).scalar_one_or_none()


_INN = {"ru": "ИНН", "uz": "STIR", "en": "TIN"}


def requisites(row: Letterhead, lang: str = "ru") -> list[str]:
    """Строки под названием компании: адрес, ИНН (на языке письма), банк; пустые не печатаются."""
    lines = [line.strip() for line in row.legal_address.splitlines() if line.strip()]
    if row.inn.strip():
        lines.append(f"{_INN.get(lang, _INN['ru'])} {row.inn.strip()}")
    lines.extend(line.strip() for line in row.bank_details.splitlines() if line.strip())
    return lines


def footer(row: Letterhead) -> list[str]:
    return [line.strip() for line in row.footer_text.splitlines() if line.strip()]
