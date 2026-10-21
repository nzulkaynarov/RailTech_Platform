"""Синхронизация доступа сотрудников к ERP (FIX-11, M3-CRM-06, ADR-0003).

Выдача доступа (`"erp"` в `users.platform_access`) → провижининг в ERP, снятие или деактивация →
отзыв сессий. Работа идёт в задачах Procrastinate (`tasks/erp_users.py`), не в пути запроса админа:
ошибки ERP не показываются пользователю, а оседают в `users.erp_sync_error` и всплывают в центре
внешних сервисов (строка «Синхронизация с ERP», ADR-0024) с оповещением и подсказкой.

Задача читает **текущее** состояние пользователя, а не снимок на момент постановки: устаревшая
задача (доступ уже сняли или выдали снова) ничего не делает, итоговое состояние ERP всегда равно
состоянию CRM. Постоянные ошибки (e-mail занят, ERP отклонил данные) фиксируются и не
повторяются; временные (ERP недоступен, 5xx, коннектор ещё не настроен — админ может подключить
ERP позже) фиксируются и пробрасываются — Procrastinate повторит по расписанию.
"""

from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.erp_permissions import erp_access
from app.domain.erp_roles import normalize_erp_roles
from app.domain.erp_sync import ERP
from app.domain.errors import ConflictError, DomainError, Reason, ValidationFailedError
from app.integrations.erp_users import ErpUsersClient, ProvisionPayload
from app.repositories import users as repo

logger = structlog.get_logger(__name__)
MAX_ERROR_LEN = 500
Outcome = Literal["done", "skipped"]
NOT_CONFIGURED_HINT = (
    "{task}: erp_not_configured: ERP не подключена — укажите адрес и сервисный токен в "
    "«Подключения» → «ERP»; задача повторится сама по расписанию"
)


class ErpAccessService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], client: ErpUsersClient) -> None:
        self._sessions = sessions
        self._client = client

    async def provision(self, user_id: int) -> Outcome:
        """Создать или обновить сотрудника в ERP по его ролям CRM."""
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
            if user is None or not user.is_active or ERP not in user.platform_access:
                return "skipped"  # доступ уже снят или пользователя нет — задача устарела
            access = erp_access(await repo.roles_of(session, user_id))
            payload = ProvisionPayload(
                crm_user_id=user.id,
                email=user.email,
                name=user.full_name,
                role=access.role,
                permissions=access.permissions,
                role_codes=tuple(normalize_erp_roles(user.erp_role_codes or [])),
            )
        await self._call(
            "erp_provision_user", user_id, lambda: self._client.provision_user(payload)
        )
        return "done"

    async def revoke(self, user_id: int) -> Outcome:
        """Отозвать все сессии сотрудника в ERP (доступ снят или пользователь деактивирован)."""
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
            if user is None:
                return "skipped"
            if user.is_active and ERP in user.platform_access:
                return "skipped"  # доступ выдали заново — отзывать нельзя
        await self._call(
            "erp_revoke_sessions", user_id, lambda: self._client.revoke_sessions(user_id)
        )
        return "done"

    async def mark_failed(self, user_id: int, message: str) -> None:
        """Ошибка постановки задачи в очередь: запись в ленту внешних сервисов."""
        await self._set_error(user_id, message)

    async def _call(self, task: str, user_id: int, call: Callable[[], Awaitable[object]]) -> None:
        try:
            await call()
        except ConflictError as exc:
            if exc.details.get("reason") != Reason.ERP_NOT_CONFIGURED:
                await self._rejected(task, user_id, exc)
                return
            # Коннектор не настроен: не постоянная ошибка — подключат, и повтор пройдёт.
            await self._set_error(user_id, NOT_CONFIGURED_HINT.format(task=task))
            logger.warning("erp_sync_not_configured", task=task, user_id=user_id)
            raise
        except ValidationFailedError as exc:
            await self._rejected(task, user_id, exc)
        except Exception as exc:
            # Временная (ERP недоступен, 5xx): записать и пробросить — Procrastinate повторит.
            await self._set_error(user_id, _describe(task, exc))
            logger.warning("erp_sync_failed", task=task, user_id=user_id, error=str(exc))
            raise
        else:
            await self._set_error(user_id, None)

    async def _rejected(self, task: str, user_id: int, exc: DomainError) -> None:
        # Постоянная ошибка: повтор ничего не изменит — запись в ленту, задача завершена.
        await self._set_error(user_id, _describe(task, exc))
        logger.warning("erp_sync_rejected", task=task, user_id=user_id, error=exc.message)

    async def _set_error(self, user_id: int, message: str | None) -> None:
        async with self._sessions() as session, session.begin():
            await repo.set_erp_sync_error(session, user_id, message)


def _describe(task: str, exc: BaseException) -> str:
    reason = exc.details.get("reason") if isinstance(exc, DomainError) else None
    code = str(reason) if reason else type(exc).__name__
    detail = exc.message if isinstance(exc, DomainError) else str(exc)
    return f"{task}: {code}: {detail}"[:MAX_ERROR_LEN]
