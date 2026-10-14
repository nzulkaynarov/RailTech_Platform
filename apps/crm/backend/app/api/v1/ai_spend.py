"""«Расходы» по ансамблю (admin, M3-CRM-09): журнал LiteLLM по дням, системам, функциям, моделям."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ContainerDep, require
from app.schemas.ai_spend import AiSpendGroup, AiSpendReport
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1/admin", tags=["spend"])


@router.get("/ai-spend", response_model=AiSpendReport)
async def get_ai_spend(
    _: Annotated[Principal, Depends(require("spend", "read"))],
    container: ContainerDep,
    date_from: Annotated[
        date | None, Query(alias="from", description="Первый день (Ташкент); по умолчанию to − 29")
    ] = None,
    date_to: Annotated[
        date | None, Query(alias="to", description="Последний день (Ташкент); по умолчанию сегодня")
    ] = None,
    group: Annotated[AiSpendGroup, Query(description="Измерение рядов `rows`")] = "day",
) -> AiSpendReport:
    """Расходы на ИИ всего ансамбля из журнала LiteLLM (`/spend/logs/v2`), кэш 60 с.

    Вызовы, токены и USD по дням, системам (`system=crm|erp`), функциям и моделям; бюджет на день
    по системе и дни превышения; деградации — вызовы, обслуженные `fallback-model`. Период — до
    90 дней, не в будущем (`422 ai_spend_period`); шлюз недоступен — `502 litellm_unavailable`.
    """
    return await container.ai_spend.report(date_from, date_to, group)
