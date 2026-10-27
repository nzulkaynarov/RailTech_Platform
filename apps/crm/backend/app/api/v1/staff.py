"""Справочные данные о коллегах, доступные любому сотруднику: фото профиля (W15-H6)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import ContainerDep
from app.api.v1.me import Settled
from app.domain.errors import NotFoundError

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


@router.get(
    "/{user_id}/avatar",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}},
)
async def get_avatar(
    user_id: Annotated[int, Path(gt=0)], _: Settled, container: ContainerDep
) -> Response:
    """Фото коллеги как есть; нет фото или сотрудник отключён — 404 (рисуются инициалы)."""
    file = await container.staff_profile.read_avatar(user_id)
    if file is None:
        raise NotFoundError("avatar not found")
    return Response(
        content=file.data,
        media_type=file.content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{file.version}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
