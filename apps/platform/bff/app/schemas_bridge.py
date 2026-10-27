"""Модели моста в старые экраны: схемы `Bridge` и `BridgeErpSso` контракта BFF (0.19.0)."""

from pydantic import BaseModel, Field


class Bridge(BaseModel):
    crm_url: str | None
    erp_url: str | None
    erp_sso: bool


class BridgeErpSso(BaseModel):
    # Токен одноразовый и живёт минуту, но всё равно секрет: не в repr и не в журнал.
    url: str = Field(repr=False)
