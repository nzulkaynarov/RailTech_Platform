"""Профиль сотрудника: роли, модули, разделы и поля по матрице (контракт: tag `me`)."""

from fastapi import APIRouter

from app.deps import AuthedDep
from app.errors import PlatformError, session_expired
from app.schemas import Me, MeUpdate, build_me
from app.session import SessionData

router = APIRouter(tags=["me"])


@router.get("/me", response_model=Me, operation_id="getMe")
async def get_me(authed: AuthedDep) -> Me:
    data = await authed.service.sync_profile(authed.sid, authed.data)
    return build_me(data)


@router.patch("/me", response_model=Me, operation_id="updateMe")
async def update_me(body: MeUpdate, authed: AuthedDep) -> Me:
    """Язык и активная роль («вид»). Права на операции от активной роли не зависят."""
    if body.active_role is not None and body.active_role not in {str(r.id) for r in authed.roles}:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Эта роль вам не назначена.",
            status_code=422,
            details={"fields": ["active_role"]},
        )

    if "language" in body.model_fields_set and body.language is not None:
        await authed.service.set_language(authed.sid, body.language)

    def apply(data: SessionData) -> None:
        if "active_role" in body.model_fields_set:
            data.active_role = int(body.active_role) if body.active_role is not None else None

    updated = await authed.service.store.update(authed.sid, apply)
    if updated is None:
        raise session_expired()
    return build_me(updated)
