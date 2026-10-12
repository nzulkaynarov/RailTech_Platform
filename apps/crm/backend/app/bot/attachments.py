"""Вложения клиентского бота: разбор видов Telegram и загрузка в S3 (SPEC §9.2, §6.4)."""

import io
from typing import Any

import structlog
from aiogram import Bot
from aiogram.types import Message

from app.integrations.s3 import ObjectStorage

logger = structlog.get_logger(__name__)

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
# Пометка вместо файла: до согласия вложения не попадают в хранилище (SPEC §6.4).
BEFORE_CONSENT: dict[str, Any] = {"stored": False, "note": "файл получен до согласия"}


def shared_text(message: Message) -> str:
    if message.contact is not None:
        contact = message.contact
        name = " ".join(filter(None, (contact.first_name, contact.last_name)))
        return f"📇 {name}: {contact.phone_number}".strip()
    if message.location is not None:
        return f"📍 {message.location.latitude:.5f}, {message.location.longitude:.5f}"
    return ""


def media_of(message: Message) -> tuple[str, str, str, int] | None:
    """file_id, имя, mime, размер вложения Telegram любого поддерживаемого вида."""
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, "photo.jpg", "image/jpeg", photo.file_size or 0
    named = message.document or message.audio or message.video or message.animation
    if named is not None:
        return (
            named.file_id,
            named.file_name or "file",
            named.mime_type or "application/octet-stream",
            named.file_size or 0,
        )
    if message.voice is not None:
        voice = message.voice
        return voice.file_id, "voice.ogg", voice.mime_type or "audio/ogg", voice.file_size or 0
    if message.video_note is not None:
        note = message.video_note
        return note.file_id, "video_note.mp4", "video/mp4", note.file_size or 0
    return None


def attachment_meta(media: tuple[str, str, str, int]) -> dict[str, Any]:
    _, name, mime, size = media
    return {"kind": "file", "name": name, "mime": mime, "size": size}


async def store_attachment(
    message: Message, bot: Bot, storage: ObjectStorage, bucket: str
) -> dict[str, Any] | None:
    media = media_of(message)
    if media is None:
        return None
    file_id, name, mime, size = media
    meta = attachment_meta(media)
    if size > MAX_ATTACHMENT_BYTES:
        return {**meta, "stored": False, "too_large": True}
    buffer = io.BytesIO()
    await bot.download(file_id, destination=buffer)
    safe = name.replace("/", "_").replace("\\", "_")[-120:]
    key = f"tg/{message.chat.id}/{message.message_id}/{safe}"
    await storage.put(bucket, key, buffer.getvalue(), mime)
    logger.info("tg_attachment_stored", chat_id=message.chat.id, size=size)
    return {**meta, "storage_key": key, "stored": True}
