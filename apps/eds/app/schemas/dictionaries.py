"""Схемы справочников (eds.yaml, тег `dictionaries`; EDS-REG)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

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


class DictionaryImportRow(Strict):
    """Строка файла, уже проверенная BFF: создать (`create`) или изменить строку с кодом (`patch`)."""

    line: Annotated[int, Field(ge=1, le=1_000_000)]
    code: Code | None = None
    create: DictionaryItemIn | None = None
    patch: DictionaryItemPatch | None = None

    @model_validator(mode="after")
    def _one_action(self) -> "DictionaryImportRow":
        if (self.create is None) == (self.patch is None):
            raise ValueError("exactly one of create and patch")
        if self.patch is not None and self.code is None:
            raise ValueError("patch needs code")
        return self


class DictionaryImportIn(Strict):
    rows: Annotated[list[DictionaryImportRow], Field(min_length=1, max_length=2000)]


class DictionaryImportRowResult(BaseModel):
    line: int
    code: str | None
    field: str | None = None
    reason: str | None = None


class DictionaryImportOut(BaseModel):
    """`applied = false` — у строк с `reason` есть ошибка, и не записано ничего."""

    applied: bool
    rows: list[DictionaryImportRowResult]
