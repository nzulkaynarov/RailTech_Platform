"""Допуск к диалогу лида (B-D18-1, W18A-P3): реестр `leads:*` или переписка `chats:*` по объекту.

Правило — `app/domain/chat_access.py`. Порядок ответа: смена временного пароля — 403; ни
`leads:<действие>`, ни `chats:<действие>` — 403 «not allowed» (как у `require`); держателю
`chats:*` чужой, обезличенный или несуществующий диалог — 404 `lead not found`.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from app.api.deps import ContainerDep, PrincipalDep, get_rbac
from app.container import Container
from app.domain.chat_access import (
    CHATS,
    INVOICED_ZONE,
    REGISTRY,
    Action,
    ChatRights,
    DialogAccess,
    dialog_access,
    needs_facts,
)
from app.domain.errors import ForbiddenError, NotFoundError, PasswordChangeRequiredError
from app.repositories import chat_access as repo
from app.security.principal import Principal
from app.security.rbac import Rbac

RbacDep = Annotated[Rbac, Depends(get_rbac)]


def rights_of(principal: Principal, rbac: Rbac, action: Action) -> ChatRights:
    """Права сотрудника на действие с диалогом: реестр, переписка и зона «Счета и оплаты»."""
    roles, platform = principal.rbac_roles, principal.platform_role_ids
    return ChatRights(
        registry=rbac.allowed(roles, REGISTRY, action, platform),
        chats=rbac.allowed(roles, CHATS, action, platform),
        invoiced_zone=rbac.allowed(roles, CHATS, INVOICED_ZONE, platform),
    )


def require_some_right(
    principal: Principal, rights: ChatRights, action: Action, named: str = REGISTRY
) -> None:
    """403 до чтения данных: временный пароль или нет ни реестра, ни переписки (`named` — какое
    право назвать в отказе)."""
    if principal.must_change_password:
        raise PasswordChangeRequiredError("change the temporary password first")
    if not rights.registry and not rights.chats:
        raise ForbiddenError(f"{named}:{action} is not allowed", resource=named)


async def check_dialog(
    principal: Principal, rbac: Rbac, container: Container, lead_id: int, action: Action
) -> DialogAccess:
    """Почему диалог открыт сотруднику; закрыт — 403 (нет прав) или 404 (не его диалог)."""
    rights = rights_of(principal, rbac, action)
    require_some_right(principal, rights, action)
    facts = None
    if needs_facts(rights):
        async with container.session_factory() as session:
            facts = await repo.dialog_facts(session, lead_id, principal.user_id)
    access = dialog_access(rights, facts)
    if access is None:
        raise NotFoundError("lead not found")
    return access


def dialog(action: Action) -> Callable[..., Awaitable[Principal]]:
    """Зависимость маршрута `/leads/{lead_id}/…` переписки: право и объектная проверка диалога."""

    async def dependency(
        lead_id: int, principal: PrincipalDep, rbac: RbacDep, container: ContainerDep
    ) -> Principal:
        await check_dialog(principal, rbac, container, lead_id, action)
        return principal

    return dependency
