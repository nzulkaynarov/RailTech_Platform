"""Маршруты `/api/v1`. Новый модуль маршрутов добавляется в `ROUTERS` — так он попадает и в приложение, и в сверку
с контрактом (`tests/test_contract_permissions.py`)."""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    approvals,
    auth,
    bus,
    dictionaries,
    documents,
    files,
    letters,
    me,
    registry,
    resolution_templates,
    signing,
)

ROUTERS: tuple[APIRouter, ...] = (
    auth.router,
    me.router,
    letters.router,
    documents.router,
    approvals.router,
    files.router,
    files.upload_router,
    registry.router,
    bus.router,
    dictionaries.router,
    resolution_templates.router,
    signing.router,
    signing.upload_router,
    ai.router,
)
