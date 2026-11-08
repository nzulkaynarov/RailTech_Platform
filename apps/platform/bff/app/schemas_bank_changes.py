"""Схемы очереди запросов на смену реквизитов контрагента (FX-4, тег `eds-payments`)."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BankChangeStatus = Literal["pending", "approved", "rejected"]


class BankChangeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    company_id: str
    company_name: str
    company_inn: str
    company_archived: bool
    status: BankChangeStatus
    stale: bool
    old_bank_details: str
    new_bank_details: str
    requested_by_name: str
    requested_by_email: str
    requested_ip: str | None
    created_at: str
    decided_at: str | None
    decided_by_name: str | None
    reject_reason: str | None


class BankChangeList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BankChangeItem]
    pending_count: int


class BankChangeRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


def to_item(raw: Mapping[str, Any]) -> BankChangeItem:
    return BankChangeItem(
        **{
            **raw,
            "id": str(raw["id"]),
            "company_id": str(raw["company_id"]),
        }
    )


def to_list(raw: Mapping[str, Any]) -> BankChangeList:
    return BankChangeList(
        items=[to_item(item) for item in raw["items"]], pending_count=raw["pending_count"]
    )
