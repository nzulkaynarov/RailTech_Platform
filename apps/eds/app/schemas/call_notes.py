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
    # Channel of the lead (`phone`, `web`, `cabinet`, `telegram`, ...): empty or `phone` - call note, else request note
    channel: Annotated[str | None, Field(max_length=32)] = None
    # Original message of the client (lead from the site, Cabinet, Telegram) and names of its attachments
    message: Annotated[str | None, Field(max_length=4000)] = None
    attachments: Annotated[list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=20)] = Field(
        default_factory=list
    )


class CallNote(BaseModel):
    id: uuid.UUID
    status: Literal["pending", "ready", "failed"]
    error: str | None
    file: FileRef | None
