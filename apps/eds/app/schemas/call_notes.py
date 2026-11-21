"""Схемы eds.yaml для записки о звонке (СЦ-6): `CallNoteIn`, `CallNote`."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import FileRef, Strict


class CallNoteIn(Strict):
    request_key: Annotated[str, Field(min_length=8, max_length=128)]
    lead: Annotated[str | None, Field(max_length=32)] = None
    caller_name: Annotated[str, Field(min_length=1, max_length=200)]
    company: Annotated[str | None, Field(max_length=200)] = None
    phone: Annotated[str | None, Field(max_length=64)] = None
    email: Annotated[str | None, Field(max_length=200)] = None
    called_at: dt.datetime
    taken_by: Annotated[str | None, Field(max_length=200)] = None
    need: Annotated[str | None, Field(max_length=4000)] = None
    lang: Literal["ru", "uz", "en"]


class CallNote(BaseModel):
    id: uuid.UUID
    status: Literal["pending", "ready", "failed"]
    error: str | None
    file: FileRef | None
