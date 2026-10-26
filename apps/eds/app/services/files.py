"""Файлы документов и писем с версиями (eds.yaml, «files»; SPEC-v3 §7.3: сканы хранятся в S3 с версионированием).

Метаданные — в базе (`files`, `file_versions`), содержимое — в S3 под ключом `files/<id>/v<версия>`. Новая версия —
тот же `id`, номер растёт, прежние версии остаются. Файл привязывается к одному письму или документу; непривязанный
видит только загрузивший. Тип проверяется по заявленному `Content-Type` и по сигнатуре содержимого (PDF, изображения,
документы Office).
"""

import mimetypes
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import EdsError, forbidden_reason, invalid_fields, not_found
from app.models import Document, Employee, FileVersion, StoredFile
from app.schemas.common import FileRef
from app.security.permissions import EdsPermission as P
from app.services import access, journal
from app.services.people import Directory, load_directory
from app.services.storage import ObjectStorage

MAX_BYTES = 25 * 1024 * 1024
_OOXML = "application/vnd.openxmlformats-officedocument."
# Допустимый тип → семейство сигнатуры содержимого.
ALLOWED: dict[str, str] = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "application/msword": "ole",
    "application/vnd.ms-excel": "ole",
    "application/vnd.ms-powerpoint": "ole",
    f"{_OOXML}wordprocessingml.document": "zip",
    f"{_OOXML}spreadsheetml.sheet": "zip",
    f"{_OOXML}presentationml.presentation": "zip",
}
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "tiff": (b"II*\x00", b"MM\x00*"),
    "ole": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "zip": (b"PK\x03\x04",),
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f/\\]")


def unsupported_type(content_type: str) -> EdsError:
    return EdsError(
        "UNSUPPORTED_MEDIA_TYPE",
        "Допустимы PDF, изображения и документы Office.",
        status_code=415,
        details={"content_type": content_type},
    )


def too_large() -> EdsError:
    return EdsError(
        "PAYLOAD_TOO_LARGE",
        "Файл больше 25 МБ.",
        status_code=413,
        details={"max_bytes": MAX_BYTES},
    )


def clean_name(raw: str | None) -> str:
    name = _CONTROL.sub("_", (raw or "").strip())[:255].strip(" .")
    return name or "file"


def resolve_content_type(declared: str | None, name: str) -> str:
    """Заявленный тип; нет или `application/octet-stream` — по расширению имени."""
    base = (declared or "").split(";")[0].strip().lower()
    if base in ("", "application/octet-stream"):
        base = (mimetypes.guess_type(name)[0] or "").lower()
    return base


def check_content(content_type: str, data: bytes) -> None:
    """415, если тип не из списка или содержимое не похоже на заявленное семейство; 413 — больше 25 МБ."""
    if len(data) > MAX_BYTES:
        raise too_large()
    family = ALLOWED.get(content_type)
    if family is None:
        raise unsupported_type(content_type)
    if family == "webp":
        ok = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    else:
        ok = any(data.startswith(sig) for sig in _SIGNATURES[family])
    if not ok:
        raise unsupported_type(content_type)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def to_ref(version: FileVersion, directory: Directory) -> FileRef:
    return FileRef(
        id=version.file_id,
        name=version.name,
        content_type=version.content_type,
        size=version.size,
        version=version.version,
        sha256=version.sha256,
        uploaded_at=version.uploaded_at,
        uploaded_by=directory.person(version.uploaded_by),
    )


@dataclass(frozen=True)
class Upload:
    name: str
    content_type: str
    data: bytes
    version_of: uuid.UUID | None = None


async def can_view_file(session: AsyncSession, employee: Employee, stored: StoredFile) -> bool:
    if stored.created_by == employee.crm_user_id:
        return True
    if stored.letter_id is not None:
        return access.can_read_letters(employee)
    if stored.document_id is not None:
        return await access.can_view_document(session, employee, stored.document_id)
    return False


async def can_add_version(session: AsyncSession, employee: Employee, stored: StoredFile) -> bool:
    """Новую версию добавляет загрузивший, автор документа или регистратор/директор писем — не любой зритель."""
    if stored.created_by == employee.crm_user_id:
        return True
    if stored.letter_id is not None:
        return access.has(employee, P.LETTERS_REGISTER) or access.has(employee, P.LETTERS_RESOLVE)
    if stored.document_id is not None:
        owner = await session.execute(select(Document.author_crm_user_id).where(Document.id == stored.document_id))
        return owner.scalar_one_or_none() == employee.crm_user_id
    return False


async def load_visible(
    session: AsyncSession, employee: Employee, file_id: uuid.UUID, *, lock: bool = False
) -> StoredFile:
    stmt = select(StoredFile).where(StoredFile.id == file_id)
    stored = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if stored is None or not await can_view_file(session, employee, stored):
        raise not_found("Файл не найден.")
    return stored


async def upload(session: AsyncSession, storage: ObjectStorage, employee: Employee, item: Upload) -> FileRef:
    """Сохранить файл или новую версию цепочки `version_of`; запись в базе и объект в S3 появляются вместе."""
    name = clean_name(item.name)
    content_type = resolve_content_type(item.content_type, name)
    check_content(content_type, item.data)
    now = clock.now()
    if item.version_of is None:
        stored = StoredFile(id=uuid.uuid4(), created_by=employee.crm_user_id, created_at=now)
        session.add(stored)
        number = 1
    else:
        stored = await load_visible(session, employee, item.version_of, lock=True)
        if not await can_add_version(session, employee, stored):
            raise forbidden_reason("not_file_owner", "Новую версию добавляет загрузивший файл или автор документа.")
        last = await session.execute(select(func.max(FileVersion.version)).where(FileVersion.file_id == stored.id))
        number = int(last.scalar_one()) + 1
    await session.flush()
    key = f"files/{stored.id}/v{number}"
    version = FileVersion(
        file_id=stored.id,
        version=number,
        name=name,
        content_type=content_type,
        size=len(item.data),
        sha256=digest(item.data),
        s3_key=key,
        uploaded_by=employee.crm_user_id,
        uploaded_at=now,
    )
    session.add(version)
    await session.flush()
    await storage.put(key, item.data, content_type)
    if stored.letter_id or stored.document_id:
        await journal.record(
            session,
            "file.version_added",
            by=employee.crm_user_id,
            letter_id=stored.letter_id,
            document_id=stored.document_id,
            file_id=stored.id,
            version=number,
        )
    return to_ref(version, await load_directory(session, [employee.crm_user_id]))


async def get_version(session: AsyncSession, file_id: uuid.UUID, version: int | None) -> FileVersion:
    stmt = select(FileVersion).where(FileVersion.file_id == file_id)
    stmt = stmt.where(FileVersion.version == version) if version else stmt.order_by(FileVersion.version.desc()).limit(1)
    found = (await session.execute(stmt)).scalar_one_or_none()
    if found is None:
        raise not_found("Версия файла не найдена.")
    return found


async def versions(session: AsyncSession, file_id: uuid.UUID) -> list[FileRef]:
    rows = list(
        (
            await session.execute(
                select(FileVersion).where(FileVersion.file_id == file_id).order_by(FileVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    directory = await load_directory(session, (r.uploaded_by for r in rows))
    return [to_ref(r, directory) for r in rows]


async def attach(
    session: AsyncSession,
    file_ids: Iterable[uuid.UUID],
    *,
    actor_id: int,
    letter_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> None:
    """Привязать файлы к письму или документу. Чужой, несуществующий или уже привязанный к другому — 422 `file_ids`."""
    wanted = list(dict.fromkeys(file_ids))
    if not wanted:
        return
    rows = {
        f.id: f
        for f in (
            await session.execute(select(StoredFile).where(StoredFile.id.in_(wanted)).with_for_update())
        ).scalars()
    }
    for file_id in wanted:
        stored = rows.get(file_id)
        same_owner = stored is not None and (
            (letter_id is not None and stored.letter_id == letter_id)
            or (document_id is not None and stored.document_id == document_id)
        )
        free = stored is not None and stored.created_by == actor_id and not (stored.letter_id or stored.document_id)
        if stored is None or not (free or same_owner):
            raise invalid_fields("Файл недоступен для привязки.", file_ids=f"{file_id}: not_attachable")
        if same_owner:
            continue
        stored.letter_id, stored.document_id = letter_id, document_id
        latest = await get_version(session, file_id, None)
        await journal.record(
            session,
            "file.attached",
            by=actor_id,
            letter_id=letter_id,
            document_id=document_id,
            file_id=file_id,
            version=latest.version,
        )


async def refs_for(
    session: AsyncSession,
    directory: Directory | None = None,
    *,
    letter_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> list[FileRef]:
    """Последние версии файлов объекта по порядку привязки."""
    owner = StoredFile.letter_id == letter_id if letter_id else StoredFile.document_id == document_id
    latest = (
        select(FileVersion.file_id, func.max(FileVersion.version).label("v")).group_by(FileVersion.file_id).subquery()
    )
    rows = list(
        (
            await session.execute(
                select(FileVersion)
                .join(latest, (FileVersion.file_id == latest.c.file_id) & (FileVersion.version == latest.c.v))
                .join(StoredFile, StoredFile.id == FileVersion.file_id)
                .where(owner)
                .order_by(StoredFile.created_at, StoredFile.id)
            )
        )
        .scalars()
        .all()
    )
    names = directory or await load_directory(session, (r.uploaded_by for r in rows))
    return [to_ref(r, names) for r in rows]
