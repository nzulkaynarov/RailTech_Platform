"""Схемы справочников как данных (контракт BFF: tag `dictionaries`; EDS-REG).

Значения и правила (код, «использовано», поля вида) — у домена-владельца; BFF добавляет к каталогу
домен и область экрана и проверяет ответ домена по этим схемам.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Коды EDS и CRM домен создаёт из названия (`^[a-z][a-z_]{0,31}$`); коды ERP задаёт человек:
# `USD`, `UZ`, `pcs`.
CODE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,49}$"
KIND = r"^[a-z][a-z-]{0,31}$"

Code = Annotated[str, StringConstraints(pattern=CODE)]
AttrValue = bool | int | str | None


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedName(BaseModel):
    ru: str
    uz: str
    en: str


class LocalizedNameIn(_In):
    ru: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    uz: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    en: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class DictionaryAttrOption(BaseModel):
    value: str
    name: LocalizedName


class DictionaryAttr(BaseModel):
    key: str
    type: Literal["boolean", "integer", "choice", "text", "decimal"]
    name: LocalizedName
    minimum: int | None = None
    maximum: int | None = None
    #: Допустимые значения `choice` (MAIL-TYPES); у EDS поля нет — `None`.
    options: list[DictionaryAttrOption] | None = None
    #: `False` — поле можно оставить пустым (CRM: вид документа EDS у типа письма).
    required: bool = True


class DictionarySource(BaseModel):
    """Открытый источник списка (валюты — ЦБ) и его последнее обновление."""

    name: LocalizedName
    synced_at: datetime | None = None


class DictionaryItemSource(DictionarySource):
    #: Строки больше нет в источнике — она не удаляется.
    missing: bool = False


class DictionarySyncResult(BaseModel):
    queued: bool


class Dictionary(BaseModel):
    kind: Annotated[str, StringConstraints(pattern=KIND)]
    owner: Literal["eds", "crm", "erp"]
    area: Literal["documents", "mail", "calc"]
    name: LocalizedName
    closed: bool
    #: `generated` — код создаёт домен из названия (EDS, CRM); `given` — код задаёт человек или
    #: файл (ERP)
    codes: Literal["generated", "given"] = "generated"
    attrs: list[DictionaryAttr]
    #: Открытый источник, который ведёт список; нет — список ведут руками
    source: DictionarySource | None = None


class DictionaryList(BaseModel):
    items: list[Dictionary]
    #: Домены, чьи справочники не ответили: список частичный, экран говорит об этом.
    unavailable: list[Literal["eds", "crm", "erp"]] = []


class DictionaryItem(BaseModel):
    code: Code
    name: LocalizedName
    attrs: dict[str, AttrValue]
    active: bool
    position: int
    used: bool | None = None
    #: Строку ведёт источник (правку руками он не перетирает); нет — строка ручная
    source: DictionaryItemSource | None = None


class DictionaryItemList(BaseModel):
    items: list[DictionaryItem]


class DictionaryItemIn(_In):
    #: Только у справочников с `codes = given` (ERP); у остальных код создаёт домен
    code: Annotated[str, StringConstraints(pattern=CODE)] | None = None
    name: LocalizedNameIn
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class DictionaryItemPatch(_In):
    name: LocalizedNameIn | None = None
    attrs: dict[str, AttrValue] | None = None
    active: bool | None = None


class DictionaryOrderIn(_In):
    codes: Annotated[list[Code], Field(min_length=1, max_length=500)]
