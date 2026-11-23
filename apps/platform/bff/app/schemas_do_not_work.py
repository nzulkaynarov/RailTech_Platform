"""Отметка «Не работать» у контрагента (план Х-8): одна форма для двух карточек."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DoNotWork(BaseModel):
    """Факты отметки: причина, кто и когда поставил, до какого дня (`None` — без срока)."""

    model_config = ConfigDict(extra="forbid")
    reason: str
    set_by: str | None
    set_at: datetime
    until: date | None
