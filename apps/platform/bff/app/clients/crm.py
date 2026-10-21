"""Клиент CRM (`crm-api`). Health CRM — `/health` в корне (apps/crm/backend/app/api/health.py)."""

from app.clients.base import BackendClient


class CrmClient(BackendClient):
    def __init__(self, base_url: str) -> None:
        super().__init__("crm", base_url, "/health")
