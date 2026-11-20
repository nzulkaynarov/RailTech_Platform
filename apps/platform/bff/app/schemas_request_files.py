"""Файл заявки клиента (СЦ-10): исходник заявки сделки ERP — в карточке письма и в расчёте."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RequestFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(ge=1)
    name: str
    uploaded_at: dt.datetime


def parse_request_files(raw: Any) -> list[RequestFile] | None:
    """Список файлов из ответа ERP: не список (старый ERP, нет ответа) — `None`; битый элемент
    пропускается."""
    if not isinstance(raw, list):
        return None
    files: list[RequestFile] = []
    for item in raw:
        try:
            files.append(RequestFile.model_validate(item))
        except ValidationError:
            continue
    return files
