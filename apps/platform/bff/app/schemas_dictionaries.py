"""Схемы справочников как данных (контракт BFF: tag `dictionaries`; EDS-REG).

Значения и правила (код, «использовано», поля вида) — у домена-владельца; BFF добавляет к каталогу
домен и область экрана и проверяет ответ домена по этим схемам.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CODE = r"^[a-z][a-z_]{0,31}$"
KIND = r"^[a-z][a-z-]{0,31}$"

Code = Annotated[str, StringConstraints(pattern=CODE)]
AttrValue = bool | int | None


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


class DictionaryAttr(BaseModel):
    key: str
    type: Literal["boolean", "integer"]
    name: LocalizedName
    minimum: int | None = None
    maximum: int | None = None


class Dictionary(BaseModel):
    kind: Annotated[str, StringConstraints(pattern=KIND)]
    owner: Literal["eds"]
    area: Literal["documents"]
    name: LocalizedName
    closed: bool
    attrs: list[DictionaryAttr]


class DictionaryList(BaseModel):
    items: list[Dictionary]


class DictionaryItem(BaseModel):
    code: Code
    name: LocalizedName
    attrs: dict[str, AttrValue]
    active: bool
    position: int
    used: bool | None = None


class DictionaryItemList(BaseModel):
    items: list[DictionaryItem]


class DictionaryItemIn(_In):
    name: LocalizedNameIn
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class DictionaryItemPatch(_In):
    name: LocalizedNameIn | None = None
    attrs: dict[str, AttrValue] | None = None
    active: bool | None = None


class DictionaryOrderIn(_In):
    codes: Annotated[list[Code], Field(min_length=1, max_length=500)]
