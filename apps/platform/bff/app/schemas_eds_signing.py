"""Права подписи (контракт BFF: `/eds/signing/…`, SIGN-2, ADR-0024): реестр и «кто подпишет».

Ids сотрудников — строки (`PersonRef` Платформы), лимит — `EdsMoney`; правила (инварианты основания,
лимит, замещение, журнал) — в EDS. Здесь — перевод форм туда и обратно и разбор ответов EDS
(`ValidationError` -> 503 в роутере).
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.feeds.models import PersonRef
from app.schemas import initials_of
from app.schemas_eds_documents import EdsMoney

Basis = Literal["charter", "order", "power_of_attorney"]
AuthorityStatus = Literal["active", "expiring", "scheduled", "expired", "revoked"]
StatusFilter = Literal["active", "expiring", "inactive", "all"]
KindCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,31}$")]
UserId = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*$")]
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
JournalAction = Literal["issued", "updated", "revoked", "file_replaced", "expiry_reminded"]


def _money_to_eds(money: EdsMoney | None) -> dict[str, Any]:
    return {
        "limit_amount": money.amount if money else None,
        "limit_currency": money.currency if money else None,
    }


class SigningAuthorityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holder_id: UserId
    kinds: Annotated[list[KindCode], Field(min_length=1, max_length=30)]
    limit: EdsMoney | None = None
    basis: Basis
    basis_number: Annotated[str | None, Field(max_length=64)] = None
    basis_date: dt.date | None = None
    valid_from: dt.date
    valid_to: dt.date | None = None
    vakolat_url: Annotated[str | None, Field(max_length=500)] = None
    note: Annotated[str | None, Field(max_length=2000)] = None

    def for_eds(self) -> dict[str, Any]:
        return {
            "crm_user_id": int(self.holder_id),
            "kinds": self.kinds,
            **_money_to_eds(self.limit),
            "basis": self.basis,
            "basis_number": self.basis_number,
            "basis_date": self.basis_date.isoformat() if self.basis_date else None,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "vakolat_url": self.vakolat_url,
            "note": self.note,
        }


class SigningAuthorityPatch(BaseModel):
    """Частичное изменение: в EDS уходит только присланное (`null` очищает необязательное поле)."""

    model_config = ConfigDict(extra="forbid")

    kinds: Annotated[list[KindCode], Field(min_length=1, max_length=30)] | None = None
    limit: EdsMoney | None = None
    basis: Basis | None = None
    basis_number: Annotated[str | None, Field(max_length=64)] = None
    basis_date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    vakolat_url: Annotated[str | None, Field(max_length=500)] = None
    note: Annotated[str | None, Field(max_length=2000)] = None

    def for_eds(self) -> dict[str, Any]:
        sent = self.model_fields_set
        body: dict[str, Any] = {}
        for name in ("kinds", "basis", "basis_number", "vakolat_url", "note"):
            if name in sent:
                body[name] = getattr(self, name)
        for name in ("basis_date", "valid_from", "valid_to"):
            if name in sent:
                value: dt.date | None = getattr(self, name)
                body[name] = value.isoformat() if value else None
        if "limit" in sent:
            body.update(_money_to_eds(self.limit))
        return body


class SigningRevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


# --- ответы EDS ---------------------------------------------------------


class _EdsPerson(BaseModel):
    crm_user_id: int
    full_name: str


class _EdsFile(BaseModel):
    name: str
    content_type: str
    size: int
    version: int
    uploaded_at: dt.datetime


class _EdsRevoked(BaseModel):
    at: dt.datetime
    by: _EdsPerson
    reason: str


class _EdsAuthority(BaseModel):
    id: uuid.UUID
    holder: _EdsPerson
    holder_position: str | None
    holder_active: bool
    kinds: list[str]
    limit_amount: str | None
    limit_currency: str | None
    basis: Basis
    basis_number: str | None
    basis_date: dt.date | None
    valid_from: dt.date
    valid_to: dt.date | None
    vakolat_url: str | None
    note: str | None
    file: _EdsFile | None
    status: AuthorityStatus
    expires_in_days: int | None
    revoked: _EdsRevoked | None
    created_by: _EdsPerson
    created_at: dt.datetime
    updated_at: dt.datetime


class _EdsEvent(BaseModel):
    at: dt.datetime
    action: JournalAction
    by: _EdsPerson | None
    comment: str | None
    details: dict[str, Any] = Field(default_factory=dict)


class _EdsDetail(_EdsAuthority):
    journal: list[_EdsEvent]


class _EdsResolvedAuthority(BaseModel):
    id: uuid.UUID
    basis: Basis
    basis_number: str | None
    basis_date: dt.date | None
    valid_to: dt.date | None
    limit_amount: str | None
    limit_currency: str | None


class _EdsCandidate(BaseModel):
    signer: _EdsPerson
    position: str | None
    acting_for: list[_EdsPerson]
    authority: _EdsResolvedAuthority
    authorities: list[_EdsResolvedAuthority]
    basis_text: str | None


class _EdsRejected(BaseModel):
    signer: _EdsPerson
    authority_id: uuid.UUID | None
    reason: RejectReason
    message: str


class _EdsStep(BaseModel):
    code: str
    crm_user_id: int | None
    text: str


class _EdsResolution(BaseModel):
    kind: str
    amount: str | None
    currency: str | None
    on_date: dt.date
    resolved: bool
    candidates: list[_EdsCandidate]
    rejected: list[_EdsRejected]
    explanation: list[_EdsStep]


class _EdsHint(BaseModel):
    has_authorities: bool
    signatory_name: str | None
    signatory_position: str | None
    director: _EdsPerson | None


# --- ответы Платформы ---------------------------------------------------------


class SigningFile(BaseModel):
    name: str
    content_type: str
    size: int
    version: int
    uploaded_at: dt.datetime


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
    limit: EdsMoney | None
    basis: Basis
    basis_number: str | None
    basis_date: dt.date | None
    valid_from: dt.date
    valid_to: dt.date | None
    vakolat_url: str | None
    note: str | None
    file: SigningFile | None
    status: AuthorityStatus
    expires_in_days: int | None
    revoked: SigningRevoked | None
    created_by: PersonRef
    created_at: dt.datetime
    updated_at: dt.datetime


class SigningChange(BaseModel):
    field: str
    before: str | None
    after: str | None


class SigningJournalEntry(BaseModel):
    at: dt.datetime
    action: JournalAction
    by: PersonRef | None
    comment: str | None
    changes: list[SigningChange]
    file_name: str | None


class SigningAuthorityDetail(SigningAuthority):
    journal: list[SigningJournalEntry]


class SigningAuthorityList(BaseModel):
    items: list[SigningAuthority]


class SigningSetupHint(BaseModel):
    has_authorities: bool
    signatory_name: str | None
    signatory_position: str | None
    director: PersonRef | None


class SigningResolvedAuthority(BaseModel):
    id: uuid.UUID
    basis: Basis
    basis_number: str | None
    basis_date: dt.date | None
    valid_to: dt.date | None
    limit: EdsMoney | None


class SignerCandidate(BaseModel):
    signer: PersonRef
    position: str | None
    acting_for: list[PersonRef]
    authority: SigningResolvedAuthority
    authorities: list[SigningResolvedAuthority]
    basis_text: str | None


class SigningRejected(BaseModel):
    signer: PersonRef
    authority_id: uuid.UUID | None
    reason: RejectReason
    message: str


class SigningResolveStep(BaseModel):
    code: str
    person_id: str | None
    text: str


class SigningResolution(BaseModel):
    kind: str
    amount: EdsMoney | None
    on_date: dt.date
    resolved: bool
    candidates: list[SignerCandidate]
    rejected: list[SigningRejected]
    explanation: list[SigningResolveStep]


def _person(p: _EdsPerson) -> PersonRef:
    return PersonRef(id=str(p.crm_user_id), name=p.full_name, initials=initials_of(p.full_name, ""))


def _money(amount: str | None, currency: str | None) -> EdsMoney | None:
    return EdsMoney(amount=amount, currency=currency) if amount and currency else None


def _changes(details: dict[str, Any]) -> list[SigningChange]:
    changed = details.get("changed")
    if not isinstance(changed, dict):
        return []

    def show(value: Any) -> str | None:
        if value is None:
            return None
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)

    result = []
    for name, pair in changed.items():
        if isinstance(pair, list) and len(pair) == 2:
            result.append(SigningChange(field=str(name), before=show(pair[0]), after=show(pair[1])))
    return result


def _authority_fields(a: _EdsAuthority) -> dict[str, Any]:
    return {
        "id": a.id,
        "holder": _person(a.holder),
        "holder_position": a.holder_position,
        "holder_active": a.holder_active,
        "kinds": a.kinds,
        "limit": _money(a.limit_amount, a.limit_currency),
        "basis": a.basis,
        "basis_number": a.basis_number,
        "basis_date": a.basis_date,
        "valid_from": a.valid_from,
        "valid_to": a.valid_to,
        "vakolat_url": a.vakolat_url,
        "note": a.note,
        "file": SigningFile(**a.file.model_dump()) if a.file else None,
        "status": a.status,
        "expires_in_days": a.expires_in_days,
        "revoked": (
            SigningRevoked(at=a.revoked.at, by=_person(a.revoked.by), reason=a.revoked.reason)
            if a.revoked
            else None
        ),
        "created_by": _person(a.created_by),
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


def to_authority(raw: Any) -> SigningAuthority:
    return SigningAuthority(**_authority_fields(_EdsAuthority.model_validate(raw)))


def to_detail(raw: Any) -> SigningAuthorityDetail:
    d = _EdsDetail.model_validate(raw)
    journal = [
        SigningJournalEntry(
            at=e.at,
            action=e.action,
            by=_person(e.by) if e.by else None,
            comment=e.comment,
            changes=_changes(e.details),
            file_name=e.details.get("name") if isinstance(e.details.get("name"), str) else None,
        )
        for e in d.journal
    ]
    return SigningAuthorityDetail(**_authority_fields(d), journal=journal)


def to_hint(raw: Any) -> SigningSetupHint:
    h = _EdsHint.model_validate(raw)
    return SigningSetupHint(
        has_authorities=h.has_authorities,
        signatory_name=h.signatory_name,
        signatory_position=h.signatory_position,
        director=_person(h.director) if h.director else None,
    )


def _resolved(a: _EdsResolvedAuthority) -> SigningResolvedAuthority:
    return SigningResolvedAuthority(
        id=a.id,
        basis=a.basis,
        basis_number=a.basis_number,
        basis_date=a.basis_date,
        valid_to=a.valid_to,
        limit=_money(a.limit_amount, a.limit_currency),
    )


def to_resolution(raw: Any) -> SigningResolution:
    r = _EdsResolution.model_validate(raw)
    return SigningResolution(
        kind=r.kind,
        amount=_money(r.amount, r.currency),
        on_date=r.on_date,
        resolved=r.resolved,
        candidates=[
            SignerCandidate(
                signer=_person(c.signer),
                position=c.position,
                acting_for=[_person(p) for p in c.acting_for],
                authority=_resolved(c.authority),
                authorities=[_resolved(a) for a in c.authorities],
                basis_text=c.basis_text,
            )
            for c in r.candidates
        ],
        rejected=[
            SigningRejected(
                signer=_person(x.signer),
                authority_id=x.authority_id,
                reason=x.reason,
                message=x.message,
            )
            for x in r.rejected
        ],
        explanation=[
            SigningResolveStep(
                code=s.code,
                person_id=None if s.crm_user_id is None else str(s.crm_user_id),
                text=s.text,
            )
            for s in r.explanation
        ],
    )
