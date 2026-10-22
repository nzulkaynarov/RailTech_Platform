# Сгенерировано apps/platform/scripts/gen_crm_models.py из packages/contracts/openapi/crm.yaml — не править руками (make -C apps/platform crm-models).

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class SsoTokenResponse(BaseModel):
    redirect_url: Annotated[str, Field(title="Redirect Url")]
    token: Annotated[str, Field(title="Token")]


class TokenResponse(BaseModel):
    access_token: Annotated[str, Field(title="Access Token")]
    expires_in: Annotated[int, Field(title="Expires In")]
    must_change_password: Annotated[bool, Field(title="Must Change Password")]
    token_type: Annotated[Literal["bearer"], Field(title="Token Type")] = "bearer"
