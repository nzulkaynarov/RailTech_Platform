"""Схемы реестра полномочий подписи и ответа «кто вправе подписать» (eds.yaml: SigningAuthority*, SigningResolution)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import Amount, Currency, FileRef, PersonRef, Strict

BasisCode = Literal["charter", "order", "power_of_attorney"]
# Состояние полномочия на сегодня: действует; действует, но скоро окончится; ещё не началось; срок вышел; отозвано.
AuthorityStatus = Literal["active", "expiring", "scheduled", "expired", "revoked"]
# Фильтр списка: «действующие» = active + expiring; «недействующие» = scheduled + expired + revoked.
StatusFilter = Literal["active", "expiring", "inactive", "all"]
KindCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,31}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True)]
# За сколько дней до окончания полномочие считается «истекающим» (экран) и уходит напоминание (задача по расписанию).
EXPIRING_DAYS = 30
REMINDER_DAYS = 14


class SigningAuthorityIn(Strict):
    crm_user_id: int
    kinds: Annotated[list[KindCode], Field(min_length=1, max_length=30)]
    limit_amount: Amount | None = None
    limit_currency: Currency | None = None
    basis: BasisCode
    basis_number: Annotated[Text | None, Field(max_length=64)] = None
    basis_date: dt.date | None = None
    valid_from: dt.date
    valid_to: dt.date | None = None
    vakolat_url: Annotated[Text | None, Field(max_length=500)] = None
    note: Annotated[Text | None, Field(max_length=2000)] = None


class SigningAuthorityPatch(Strict):
    """Частичное изменение: переданное поле меняется, непереданное остаётся; `null` очищает необязательное поле.
    Владельца (`crm_user_id`) не меняют: другому человеку полномочие выдают заново."""

    kinds: Annotated[list[KindCode], Field(min_length=1, max_length=30)] | None = None
    limit_amount: Amount | None = None
    limit_currency: Currency | None = None
    basis: BasisCode | None = None
    basis_number: Annotated[Text | None, Field(max_length=64)] = None
    basis_date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    vakolat_url: Annotated[Text | None, Field(max_length=500)] = None
    note: Annotated[Text | None, Field(max_length=2000)] = None


class SigningRevokeIn(Strict):
    reason: Annotated[Text, Field(min_length=3, max_length=1000)]


class SigningRevoked(BaseModel):
    at: dt.datetime
    by: PersonRef
    reason: str


class SigningAuthority(BaseModel):
    id: uuid.UUID
    holder: PersonRef
    holder_position: str | None
    holder_active: bool
    kinds: list[str]
    limit_amount: Amount | None
    limit_currency: Currency | None
    basis: BasisCode
    basis_number: str | None
    basis_date: dt.date | None
    valid_from: dt.date
    valid_to: dt.date | None
    vakolat_url: str | None
    note: str | None
    file: FileRef | None
    status: AuthorityStatus
    expires_in_days: int | None
    revoked: SigningRevoked | None
    created_by: PersonRef
    created_at: dt.datetime
    updated_at: dt.datetime


class SigningAuthorityEvent(BaseModel):
    at: dt.datetime
    action: Literal["issued", "updated", "revoked", "file_replaced", "expiry_reminded"]
    by: PersonRef | None
    comment: str | None
    details: dict[str, object]


class SigningAuthorityDetail(SigningAuthority):
    journal: list[SigningAuthorityEvent]


class SigningAuthorityList(BaseModel):
    items: list[SigningAuthority]


class SigningSetupHint(BaseModel):
    """Подсказка первого запуска: кто подписывает по уставу (из бланка компании) и есть ли уже хоть одно полномочие."""

    has_authorities: bool
    signatory_name: str | None
    signatory_position: str | None
    director: PersonRef | None


# --- «кто вправе подписать» ------------------------------------------------------------------------------------------


class ResolvedAuthority(BaseModel):
    id: uuid.UUID
    basis: BasisCode
    basis_number: str | None
    basis_date: dt.date | None
    valid_to: dt.date | None
    limit_amount: Amount | None
    limit_currency: Currency | None


class SignerCandidate(BaseModel):
    """Кто вправе подписать: полномочие всегда своё. `acting_for` — отсутствующие держатели, чья задача подписи
    пришла этому человеку по замещению (пусто — он подписывает как держатель)."""

    signer: PersonRef
    position: str | None
    acting_for: list[PersonRef]
    authority: ResolvedAuthority
    authorities: list[ResolvedAuthority]
    basis_text: str | None


RejectReason = Literal[
    "revoked",
    "not_started",
    "expired",
    "limit_exceeded",
    "currency_mismatch",
    "holder_inactive",
    "absent",
    "deputy_without_authority",
    "deputy_loop",
]


class RejectedSigner(BaseModel):
    signer: PersonRef
    authority_id: uuid.UUID | None
    reason: RejectReason
    message: str


class ResolveStep(BaseModel):
    code: str
    crm_user_id: int | None
    text: str


class SigningResolution(BaseModel):
    """Ответ «кто вправе подписать вид X на сумму Y на дату D»; `explanation` — для экрана и будущего помощника."""

    kind: str
    amount: Amount | None
    currency: Currency | None
    on_date: dt.date
    resolved: bool
    candidates: list[SignerCandidate]
    rejected: list[RejectedSigner]
    explanation: list[ResolveStep]


class SignerCheck(BaseModel):
    """Вправе ли конкретный сотрудник подписать: `allowed` и причина отказа текстом."""

    allowed: bool
    candidate: SignerCandidate | None
    reason: RejectReason | Literal["no_authority"] | None
    message: str
