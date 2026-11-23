"""Маршруты `/api/v1`. Новый модуль маршрутов добавляется в `ROUTERS` — так он попадает и в приложение, и в сверку
с контрактом (`tests/test_contract_permissions.py`)."""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    approvals,
    auth,
    bus,
    call_notes,
    dictionaries,
    documents,
    files,
    letter_templates,
    letters,
    me,
    numbering,
    registry,
    resolution_templates,
    service,
    signing,
    waiting,
)

ROUTERS: tuple[APIRouter, ...] = (
    auth.router,
    me.router,
    letters.router,
    documents.router,
    approvals.router,
    files.router,
    files.upload_router,
    call_notes.router,
    registry.router,
    numbering.router,
    bus.router,
    dictionaries.router,
    letter_templates.router,
    letter_templates.previews,
    resolution_templates.router,
    signing.router,
    signing.upload_router,
    ai.router,
    service.router,
    waiting.router,
)
