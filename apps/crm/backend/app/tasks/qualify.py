"""Задача квалификатора (SPEC §7.2): на каждое сообщение, с батчингом 5 с.

`queueing_lock` не даёт поставить вторую задачу, пока первая ждёт старта, —
сообщения, пришедшие за эти 5 с, обработает одна задача. `lock` запрещает
параллельный прогон по одному лиду.
"""

from procrastinate import RetryStrategy
from procrastinate.exceptions import AlreadyEnqueued

from app.agents.llm import ChatModel
from app.agents.qualifier.graph import QualifierAgent
from app.container import Container, get_container
from app.services.budget import BudgetedModel
from app.services.qualifier import QualifierService
from app.tasks.queue import queue

DELAY_S = 5


async def build_qualifier_service(c: Container) -> QualifierService:
    return QualifierService(
        c.session_factory,
        c.settings_service,
        QualifierAgent(
            BudgetedModel(
                ChatModel(c.llm, "qualifier-model", usage=c.usage_recorder),
                None,
                c.budget_guard,
                alias="qualifier-model",
            )
        ),
        c.lead_messenger,  # тот же отправитель, что у CRM: уважает TELEGRAM_DRY_RUN
        on_escalation=_escalated,
    )


async def _escalated(lead_id: int, escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id)


@queue.task(
    name="qualify_lead",
    queue="qualifier",
    retry=RetryStrategy(max_attempts=2, wait=10),
)
async def qualify_lead(lead_id: int) -> int | None:
    return await (await build_qualifier_service(get_container())).run(lead_id)


async def enqueue_qualify(lead_id: int) -> bool:
    """Поставить квалификацию лида через 5 с. False — уже стоит в очереди (батчинг)."""
    try:
        await qualify_lead.configure(
            lock=f"qualify-lead-{lead_id}",
            queueing_lock=f"qualify-lead-{lead_id}",
            schedule_in={"seconds": DELAY_S},
        ).defer_async(lead_id=lead_id)
    except AlreadyEnqueued:
        return False
    return True
