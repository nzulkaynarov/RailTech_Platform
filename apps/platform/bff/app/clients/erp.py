"""Клиент ERP (`erp-backend`). Health ERP — `/health/` в корне (apps/erp/backend/core/urls.py)."""

from app.clients.base import BackendClient


class ErpClient(BackendClient):
    def __init__(self, base_url: str) -> None:
        super().__init__("erp", base_url, "/health/")
