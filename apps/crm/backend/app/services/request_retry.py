"""«Повторить отправку в ERP» для заявки CRM с ошибкой (B-082, W16-D1-2b).

Заявка («Создать заявку», `deals.request_summary` есть) в `erp_request_status = failed` снова
становится `pending`, и та же задача `erp_create_request` ставится в очередь с тем же
`crm_request_id` (id строки `deals`): ERP идемпотентна по нему, второй заявки не будет. Статус
меняется под блокировкой строки (`FOR UPDATE`): двойной клик даёт одну задачу — второй вызов видит
`pending` и получает 409 `request_not_failed`. Постоянная ошибка `erp_request_conflict` (данные
заявки изменились после первой отправки) повтором не лечится — 409 `request_not_retryable`.
Бэк-офис не в режиме ERP — 409 `erp_not_configured`, как у «Создать заявку».

Очередь отказала (не «такая задача уже ждёт» — это обрабатывает сама постановка) — заявка снова
`failed` с `enqueue_failed` и записью аудита, ответ `erp_request_status = failed`: кнопка повтора
остаётся, заявка не зависает в `pending` без задачи.

Владение заявкой не проверяется сознательно — как у `create_for_client`: повтор доступен любому с
`clients:write` (руководитель подхватывает заявку отсутствующего менеджера).
"""

from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.backoffice import BackofficeMode
from app.domain.erp_handoff import PENDING
from app.domain.errors import ConflictError, NotFoundError, Reason
from app.models.deals import Deal
from app.schemas.client_requests import RequestRetried
from app.security import audit
from app.security.principal import Principal

logger = structlog.get_logger(__name__)

RequestEnqueue = Callable[[int, int, int], Awaitable[object]]
BackofficeModeProvider = Callable[[], Awaitable[BackofficeMode]]
PERMANENT = frozenset({Reason.ERP_REQUEST_CONFLICT.value})


class RequestRetryService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        enqueue: RequestEnqueue | None,
        *,
        backoffice_mode: BackofficeModeProvider,
    ) -> None:
        self._sessions = sessions
        self._enqueue = enqueue
        self._mode = backoffice_mode

    async def retry(self, who: Principal, deal_id: int) -> RequestRetried:
        if self._enqueue is None or await self._mode() != BackofficeMode.ERP:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is None or deal.request_summary is None or deal.client_id is None:
                raise NotFoundError("request not found")
            if deal.erp_request_status != "failed":
                raise ConflictError("the request is not in error", reason=Reason.REQUEST_NOT_FAILED)
            if deal.erp_request_error in PERMANENT:
                raise ConflictError(
                    "ERP: заявка уже отправлялась с другими данными — повтор не поможет, "
                    "создайте заявку заново",
                    reason=Reason.REQUEST_NOT_RETRYABLE,
                )
            previous = deal.erp_request_error
            deal.erp_request_status, deal.erp_request_error = PENDING, None
            await audit.record(
                session,
                who.actor,
                "deal.erp_request_retry",
                "deal",
                deal.id,
                after={"previous_error": previous},
            )
            client_id = deal.client_id
        try:
            await self._enqueue(deal_id, client_id, who.user_id)
        except Exception as exc:
            logger.exception("erp_request_retry_enqueue_failed", deal_id=deal_id)
            await self._mark_failed(deal_id, str(exc))
            return RequestRetried(deal_id=deal_id, client_id=client_id, erp_request_status="failed")
        return RequestRetried(deal_id=deal_id, client_id=client_id)

    async def _mark_failed(self, deal_id: int, detail: str) -> None:
        """Как у «Создать заявку»: задача не встала — заявка снова в ошибке, повтор доступен."""
        async with self._sessions() as session, session.begin():
            deal = await session.get(Deal, deal_id, with_for_update=True)
            if deal is not None and deal.erp_request_status == PENDING:
                deal.erp_request_status, deal.erp_request_error = "failed", "enqueue_failed"
                await audit.record(
                    session,
                    audit.Actor.system(),
                    "deal.erp_request_failed",
                    "deal",
                    deal_id,
                    after={"code": "enqueue_failed", "detail": detail[:500]},
                )
