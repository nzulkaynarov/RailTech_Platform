"""Шаблоны быстрых ответов (аудит 2026-10-12 §5): читают менеджеры, правит админ, с аудитом."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import ContainerDep, require
from app.domain.errors import NotFoundError
from app.models.reply_templates import ReplyTemplate
from app.schemas.kb_admin import Created
from app.schemas.leads import ActionResult
from app.schemas.reply_templates import ReplyTemplateIn, ReplyTemplateOut
from app.security import audit
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1/reply-templates", tags=["reply-templates"])

Reader = Annotated[Principal, Depends(require("reply_templates", "read"))]
Writer = Annotated[Principal, Depends(require("reply_templates", "write"))]


def _out(row: ReplyTemplate) -> ReplyTemplateOut:
    return ReplyTemplateOut(id=row.id, title=row.title, text=row.text, updated_at=row.updated_at)


@router.get("", response_model=list[ReplyTemplateOut])
async def list_reply_templates(_: Reader, container: ContainerDep) -> list[ReplyTemplateOut]:
    """Шаблоны по названию; текст на ru/uz/en с подстановками `{name}`, `{manager}`."""
    async with container.session_factory() as session:
        rows = await session.scalars(select(ReplyTemplate).order_by(ReplyTemplate.title))
        return [_out(r) for r in rows]


@router.post("", response_model=Created, status_code=status.HTTP_201_CREATED)
async def create_reply_template(
    body: ReplyTemplateIn, who: Writer, container: ContainerDep
) -> Created:
    payload = body.model_dump(mode="json")
    async with container.session_factory() as session, session.begin():
        row = ReplyTemplate(title=body.title.strip(), text=payload["text"], created_by=who.user_id)
        session.add(row)
        await session.flush()
        await audit.record(
            session, who.actor, "reply_template.create", "reply_template", row.id, after=payload
        )
        return Created(id=row.id)


@router.put("/{template_id}", response_model=ActionResult)
async def update_reply_template(
    template_id: int, body: ReplyTemplateIn, who: Writer, container: ContainerDep
) -> ActionResult:
    payload = body.model_dump(mode="json")
    async with container.session_factory() as session, session.begin():
        row = await session.get(ReplyTemplate, template_id, with_for_update=True)
        if row is None:
            raise NotFoundError("reply template not found")
        before = {"title": row.title, "text": row.text}
        row.title, row.text = body.title.strip(), payload["text"]
        await audit.record(
            session,
            who.actor,
            "reply_template.update",
            "reply_template",
            template_id,
            before=before,
            after=payload,
        )
    return ActionResult()


@router.delete("/{template_id}", response_model=ActionResult)
async def delete_reply_template(
    template_id: int, who: Writer, container: ContainerDep
) -> ActionResult:
    async with container.session_factory() as session, session.begin():
        row = await session.get(ReplyTemplate, template_id, with_for_update=True)
        if row is None:
            raise NotFoundError("reply template not found")
        before = {"title": row.title, "text": row.text}
        await session.delete(row)
        await audit.record(
            session,
            who.actor,
            "reply_template.delete",
            "reply_template",
            template_id,
            before=before,
        )
    return ActionResult()
