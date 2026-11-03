"""DTO типов входящих писем (MAIL-TYPES): справочник как ресурс домена, правила отправителя,
действия
по письму.

Ресурс `/api/v1/dictionaries` — тот же, что у EDS (EDS-REG): Платформа показывает справочники всех
доменов одним
экраном. Здесь у значения три поля вида — `default_action`, `color`, `icon`, все три — выбор из
закрытого списка кода
(`type = choice`, варианты в `options`).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.mail_types import CODE_PATTERN

DICTIONARY_KIND = r"^[a-z][a-z-]{0,31}$"
NameRu = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NameOther = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
AttrValue = bool | int | str | None
Code = Annotated[str, StringConstraints(pattern=CODE_PATTERN)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedName(BaseModel):
    ru: str
    uz: str
    en: str


class LocalizedNameIn(_Strict):
    ru: NameRu
    uz: NameOther = ""
    en: NameOther = ""


class DictionaryAttrOption(BaseModel):
    value: str
    name: LocalizedName


class DictionaryAttr(BaseModel):
    key: str
    type: Literal["boolean", "integer", "choice"]
    name: LocalizedName
    minimum: int | None = None
    maximum: int | None = None
    options: list[DictionaryAttrOption] | None = Field(
        default=None,
        description="Допустимые значения `type = choice` (закрытый список кода; пусто — варианты "
        "подставляет Платформа из справочника другого домена)",
    )
    required: bool = Field(default=True, description="`false` — поле можно оставить пустым")


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


class DictionaryItemIn(_Strict):
    name: LocalizedNameIn
    attrs: dict[str, AttrValue] = Field(default_factory=dict)


class DictionaryItemPatch(_Strict):
    name: LocalizedNameIn | None = None
    attrs: dict[str, AttrValue] | None = None
    active: bool | None = None


class DictionaryOrderIn(_Strict):
    codes: Annotated[list[Code], Field(min_length=1, max_length=500)]


class InboundMailType(BaseModel):
    """Тип письма в списке и карточке: название, тег и действие по умолчанию (основная кнопка
    карточки)."""

    code: str
    name: LocalizedName
    color: str
    icon: str
    default_action: str
    letter_kind: str | None = Field(
        default=None,
        description="Вид документа EDS (код): им форма ВХ из письма этого типа предзаполняется",
    )
    active: bool = Field(
        description="Тип отключён: у письма остаётся, предлагать его больше не будем"
    )
    source: Literal["rule", "ai", "manual"] = Field(
        description="Кто выбрал: правило отправителя, помощник (человек подтверждает) или человек"
    )


class MailSenderRule(BaseModel):
    id: int
    pattern: str = Field(description="Адрес `ivan@firma.uz` или домен `firma.uz` (с поддоменами)")
    type_code: str
    created_at: datetime
    created_by: str | None = Field(default=None, description="Кто создал (имя сотрудника)")


class MailSenderRuleList(BaseModel):
    items: list[MailSenderRule]


class MailSenderRuleIn(_Strict):
    pattern: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    type_code: Code
    mail_id: int | None = Field(
        default=None,
        ge=1,
        description="Письмо, из карточки которого создано правило: тип ставится и ему",
    )


class MailSenderRuleOut(MailSenderRule):
    applied: int = Field(description="Сколько открытых писем «Новые» получили тип по этому правилу")
    caution: Literal["public_domain"] | None = Field(
        default=None,
        description="`public_domain` — шаблон на публичный почтовый сервис (gmail.com, mail.ru …): "
        "правило поймает письма кого угодно",
    )


class InboundMailTypeIn(_Strict):
    type_code: Code | None = Field(description="Код типа или `null` — снять тип")


HandoverPurpose = Literal["payments", "price"]


class InboundMailHandoverIn(_Strict):
    user_id: int = Field(ge=1)
    purpose: HandoverPurpose = Field(
        default="payments",
        description="`payments` — счёт тому, кто подтверждает оплату; `price` — прайс тому, кто "
        "загружает прайсы поставщиков",
    )


class InboundMailHandoverTarget(BaseModel):
    id: int
    name: str


class InboundMailHandoverTargets(BaseModel):
    items: list[InboundMailHandoverTarget]
