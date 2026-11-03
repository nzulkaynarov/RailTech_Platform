"""Схемы справочников (eds.yaml, тег `dictionaries`; EDS-REG)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import Strict

DICTIONARY_CODE = r"^[a-z][a-z_]{0,31}$"
DICTIONARY_KIND = r"^[a-z][a-z-]{0,31}$"

Code = Annotated[str, StringConstraints(pattern=DICTIONARY_CODE)]
NameRu = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NameOther = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
AttrValue = bool | int | None


class LocalizedName(BaseModel):
    ru: str
    uz: str
    en: str


class LocalizedNameIn(Strict):
    ru: NameRu
    uz: NameOther = ""
    en: NameOther = ""


class DictionaryAttr(BaseModel):
    key: str
    type: Literal["boolean", "integer"]
    name: LocalizedName
    minimum: int | None = None
    maximum: int | None = None


class Dictionary(BaseModel):
    kind: str
    name: LocalizedName
    closed: bool
    attrs: list[DictionaryAttr]


class DictionaryList(BaseModel):
    items: list[Dictionary]


class DictionaryItem(BaseModel):
    code: str
    name: LocalizedName
    attrs: dict[str, AttrValue]
    active: bool
    position: int
    used: bool | None = None


class DictionaryItemList(BaseModel):
    items: list[DictionaryItem]


class DictionaryItemIn(Strict):
    name: LocalizedNameIn
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class DictionaryItemPatch(Strict):
    name: LocalizedNameIn | None = None
    attrs: dict[str, AttrValue] | None = None
    active: bool | None = None


class DictionaryOrderIn(Strict):
    codes: Annotated[list[Code], Field(min_length=1, max_length=500)]
