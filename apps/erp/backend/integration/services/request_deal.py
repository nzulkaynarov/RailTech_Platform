"""Единственное место, где создаётся сделка-заявка со сутью: Кабинет, мастер Платформы, передача лида и MCP.

Клиент в Кабинете видит название сделки и полный текст (`PortalRequestSummary`): без них заявка, заведённая сотрудником или
ботом, выглядела «Заявка: <компания>» без сути (ПРАВДА-2). Любой путь, создающий заявку, обязан идти через `create_request_deal`.
"""

from __future__ import annotations

from typing import Any

from portal.models import PortalRequestSummary

from crm.models import Deal


def short_title(summary: str) -> str:
    """Название сделки из сути запроса: одна строка, не длиннее поля `Deal.title`."""
    title = " ".join(summary.split())
    max_length = Deal._meta.get_field("title").max_length
    return title if len(title) <= max_length else title[: max_length - 1].rstrip() + "…"


def create_request_deal(*, company, summary: str, **fields: Any) -> Deal:
    """Сохраняет сделку-заявку: название — суть одной строкой, полный текст — `PortalRequestSummary`."""
    deal = Deal(company=company, title=short_title(summary) or f"Заявка: {company.name}", **fields)
    deal.save()
    PortalRequestSummary.objects.create(deal=deal, text=summary)
    return deal
