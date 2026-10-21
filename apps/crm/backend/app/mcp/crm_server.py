"""crm-mcp: контекст лида и действия агента над CRM (SPEC §7.1, ADR-0008).

Инструменты: `get_lead_context()`, `update_qualification(patch)` (prospect),
`request_callback(preferred_time?)`. Лид — только из подписанного контекста.
"""

from datetime import UTC, datetime
from typing import Any, Final

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.container import Container, get_container
from app.domain import erp_handover
from app.domain.qualification import Qualification, merge_qualification
from app.mcp.common import build_app, require_context, serve
from app.models.clients import ServiceRequest
from app.repositories import leads as repo

SERVICE: Final = "crm-mcp"
PORT: Final = 8102
HISTORY_LIMIT: Final = 20


class HistoryItem(BaseModel):
    role: str
    text: str


class LeadContext(BaseModel):
    lead_id: int
    display_name: str
    language: str
    stage: str
    score: int
    owner_mode: str
    need_summary: str | None
    product_interest: list[str]
    qualification: dict[str, Any]
    notes: list[str]
    history: list[HistoryItem]
    customer: bool


class QualificationPatch(BaseModel):
    company: str | None = Field(default=None, max_length=255)
    company_size: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=128)
    timeline: str | None = Field(default=None, description="<1m | <3m | <12m | >12m")
    decision_role: str | None = Field(
        default=None, description="decision_maker | influencer | researcher"
    )
    budget_hint: str | None = Field(default=None, max_length=255)


def create_server(container: Container | None = None) -> MCPServer[Any]:
    c = container or get_container()
    server: MCPServer[Any] = MCPServer("crm-mcp", instructions="Контекст лида и действия в CRM.")

    @server.tool(description="Контекст текущего лида: стадия, квалификация, заметки, история.")
    async def get_lead_context(ctx: Context[Any, Any]) -> LeadContext:
        agent = require_context(ctx, c.settings)
        async with c.session_factory() as session:
            lead = await repo.get_lead(session, agent.lead_id)
            if lead is None:
                raise ToolError("lead not found")
            messages = await repo.recent_messages(session, lead.id, HISTORY_LIMIT)
            notes = await repo.bot_notes(session, lead.id)
        if agent.mode == "prospect":
            # Клиента деактивировали: ответы с данными ERP (счета, суммы, сроки) лиду не отдаём.
            messages = [m for m in messages if not (m.role == "bot" and m.meta.get("erp_used"))]
        return LeadContext(
            lead_id=lead.id,
            display_name=lead.display_name,
            language=lead.language,
            stage=lead.stage,
            score=lead.score,
            owner_mode=lead.owner_mode,
            need_summary=lead.need_summary,
            product_interest=list(lead.product_interest or []),
            qualification=dict(lead.qualification or {}),
            notes=[n.text for n in notes],
            history=[HistoryItem(role=m.role, text=m.text) for m in messages],
            customer=agent.mode == "customer",
        )

    @server.tool(
        description="Записать сведения, которые клиент сам сообщил: компания, роль, сроки, бюджет."
    )
    async def update_qualification(
        patch: QualificationPatch, ctx: Context[Any, Any]
    ) -> dict[str, Any]:
        agent = require_context(ctx, c.settings)
        if agent.mode != "prospect":
            raise ToolError("not available in this mode")
        update = Qualification.model_validate(patch.model_dump(exclude_none=True))
        async with c.session_factory() as session, session.begin():
            lead = await repo.get_lead(session, agent.lead_id, for_update=True)
            if lead is None:
                raise ToolError("lead not found")
            current = dict(lead.qualification or {})
            known = Qualification.model_validate(
                {k: v for k, v in current.items() if k in Qualification.model_fields}
            )
            current.update(merge_qualification(known, update).model_dump(exclude_none=True))
            lead.qualification = current
        return {"ok": True}

    @server.tool(description="Клиент сам попросил, чтобы с ним связались (звонок/сообщение).")
    async def request_callback(
        ctx: Context[Any, Any], preferred_time: str | None = None
    ) -> dict[str, Any]:
        agent = require_context(ctx, c.settings)
        async with c.session_factory() as session, session.begin():
            lead = await repo.get_lead(session, agent.lead_id, for_update=True)
            if lead is None:
                raise ToolError("lead not found")
            qualification = dict(lead.qualification or {})
            signals = dict(qualification.get("signals") or {})
            signals["requested_contact"] = True
            qualification["signals"] = signals
            qualification["callback"] = {
                "preferred_time": (preferred_time or "")[:200] or None,
                "requested_at": datetime.now(UTC).isoformat(),
            }
            lead.qualification = qualification
        return {"ok": True, "callback_requested": True}

    @server.tool(
        description="Клиент сообщил о проблеме или спросил статус работ: создать сервисный запрос."
    )
    async def create_service_request(
        summary: str, ctx: Context[Any, Any], source: str | None = None
    ) -> dict[str, Any]:
        agent = require_context(ctx, c.settings)
        if agent.mode != "customer" or agent.client_id is None:
            raise ToolError("not available in this mode")
        async with c.session_factory() as session, session.begin():
            if source == erp_handover.SOURCE:
                # «ERP недоступен»: один запрос на клиента за сутки, повторы получают его номер.
                since = datetime.now(UTC) - erp_handover.DEDUPE_WINDOW
                existing = await session.scalar(
                    select(ServiceRequest.id)
                    .where(
                        ServiceRequest.client_id == agent.client_id,
                        ServiceRequest.created_at > since,
                        ServiceRequest.summary.startswith(erp_handover.SUMMARY_PREFIX),
                    )
                    .order_by(ServiceRequest.id.desc())
                    .limit(1)
                )
                if existing is not None:
                    return {"ok": True, "service_request_id": existing, "deduplicated": True}
            row = ServiceRequest(
                client_id=agent.client_id, lead_id=agent.lead_id, summary=summary.strip()[:2000]
            )
            session.add(row)
            await session.flush()
            return {"ok": True, "service_request_id": row.id}

    return server


def main() -> None:
    serve(build_app(create_server(), SERVICE, PORT), PORT)
