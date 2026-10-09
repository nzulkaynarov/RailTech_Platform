"""Webhook Telegram (prod): проверка `secret_token`, обработка апдейта в фоне (SPEC §9.2)."""

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.bot.runtime import BotRuntime

router = APIRouter(include_in_schema=False)


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> Response:
    runtime: BotRuntime | None = getattr(request.app.state, "bot", None)
    if runtime is None or not runtime.secret_matches(secret):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    update: dict[str, Any] = await request.json()
    runtime.feed(update)
    return Response(status_code=status.HTTP_200_OK)
