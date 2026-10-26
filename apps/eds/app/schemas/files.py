"""Схемы файлов (eds.yaml: FileVersions); FileRef — в `common`."""

from pydantic import BaseModel

from app.schemas.common import FileRef


class FileVersions(BaseModel):
    items: list[FileRef]
