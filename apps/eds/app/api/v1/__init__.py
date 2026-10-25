"""Маршруты `/api/v1`. Новый модуль маршрутов добавляется в `ROUTERS` — так он попадает и в приложение, и в сверку
с контрактом (`tests/test_contract_permissions.py`)."""

from fastapi import APIRouter

from app.api.v1 import approvals, auth, documents, letters, me

ROUTERS: tuple[APIRouter, ...] = (auth.router, me.router, letters.router, documents.router, approvals.router)
