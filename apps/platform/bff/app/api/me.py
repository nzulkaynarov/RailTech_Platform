"""Профиль сотрудника: роли, модули, разделы и поля по матрице (контракт: tag `me`)."""

from fastapi import APIRouter

from app.deps import AuthedDep
from app.errors import session_expired
from app.schemas import Me, MeUpdate, build_me

router = APIRouter(tags=["me"])


@router.get("/me", response_model=Me, operation_id="getMe")
async def get_me(authed: AuthedDep) -> Me:
    data = await authed.service.sync_profile(authed.sid, authed.data)
    return build_me(data)


@router.patch("/me", response_model=Me, operation_id="updateMe")
async def update_me(body: MeUpdate, authed: AuthedDep) -> Me:
    """Язык интерфейса. Активной роли нет: сотрудник работает со всем, что ему делегировано."""
    if body.language is not None:
        await authed.service.set_language(authed.sid, body.language)
    updated = await authed.service.store.update(authed.sid, lambda data: None)
    if updated is None:
        raise session_expired()
    return build_me(updated)
