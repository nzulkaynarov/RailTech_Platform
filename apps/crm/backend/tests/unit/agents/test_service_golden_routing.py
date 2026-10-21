"""Маршрутизация golden-кейсов сервисного режима на подставной модели (без платных вызовов).

Модель отвечает текстом без вызовов инструментов: проверяется то, что решает код, — какое действие
выбрано для сообщения и видит ли модель инструменты ERP (клиенту с кейсом `erp` — да, лиду и кейсу
без `erp` — нет). Формулировки и числа ответа проверяет платный eval (`evals/test_eval.py`).
"""

from typing import Any

import pytest

from app.agents.dialog.erp_tools import ERP_TOOL_NAMES
from app.agents.dialog.graph import DialogAgent
from app.schemas.settings import AppSettings
from app.security.erp_agent_context import ErpScope
from evals.golden import GoldenCase, load_cases
from tests.unit.agents.fakes import FakeErp, FakeTools, ToolsModel, kb, lead, reply

CASES = [c for c in load_cases() if c.category == "service_mode"]


class CaseTools(FakeTools):
    """crm/docs-mcp кейса: лид, пустая база знаний и документы клиента из YAML."""

    def __init__(self, case: GoldenCase) -> None:
        super().__init__(lead(stage=case.stage, customer=case.mode == "customer"), kb(0.2))
        self.case = case

    async def call(self, server: str, tool: str, args: dict[str, Any], context: str) -> Any:
        if tool == "search_documents":
            return [
                {"document_id": d.document_id, "title": d.title, "type": d.type, "number": d.number}
                for d in self.case.documents
                if not args.get("type") or d.type == args["type"]
            ]
        if tool == "get_document_link":
            return {"document_id": args["document_id"], "title": "Документ", "url": "http://docs"}
        return await super().call(server, tool, args, context)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_case_routes_as_expected(case: GoldenCase) -> None:
    model = ToolsModel(reply("Ответ."))
    erp = FakeErp(**(case.erp.tools if case.erp else {}))
    agent = DialogAgent(CaseTools(case), model, erp=erp if case.erp else None)
    result = await agent.run(
        lead_id=1,
        text=case.message,
        language=case.language,
        context_token="t",
        settings=AppSettings(),
        stage=case.stage,
        mode=case.mode,
        erp_scope=ErpScope(1, 1, case.language) if case.erp else None,
    )
    assert result.action.value in case.expect.actions
    assert erp.calls == []  # модель инструментов не вызывала
    if model.offered:
        assert bool(model.offered[0] & ERP_TOOL_NAMES) is bool(case.erp)
