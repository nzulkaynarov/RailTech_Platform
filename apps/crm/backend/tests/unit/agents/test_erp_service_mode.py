"""Сервисный режим бота через erp-mcp (M3-CRM-07): маршрутизация на подставных модели и ERP.

Проверяется то, что решает код: какие инструменты и с каким контекстом вызваны, что видит модель,
что уходит клиенту при отказе ERP и при числе, которого нет в данных. Качество формулировок
(faithfulness) проверяют golden-кейсы `evals/golden/service.yaml` — платным прогоном по «да».
"""

from typing import Any

import pytest

from app.agents.dialog.erp_tools import ERP_TOOL_NAMES
from app.agents.dialog.graph import DialogAgent
from app.agents.dialog.state import DialogResult
from app.agents.erp_mcp import ErpMcpError
from app.agents.llm import ToolCall
from app.domain.dialog_policy import Action
from app.schemas.settings import AppSettings
from app.security.erp_agent_context import ErpScope
from tests.unit.agents.fakes import FakeErp, FakeTools, ToolsModel, kb, lead, reply

SETTINGS = AppSettings()
SCOPE = ErpScope(crm_client_id=7, erp_company_id=42, language="ru")
DEAL = {"erp_deal_id": 5, "number": "D-5", "title": "Трекеры RT-Track", "stage": "invoiced"}
STATUS = {
    **DEAL,
    "invoices": [{"number": "77", "amount": "12500000.00", "currency": "UZS", "status": "issued"}],
}
DELIVERY = [
    {"erp_deal_id": 5, "line_no": 1, "title": "Трекер", "status": "shipped", "eta": "2026-10-25"}
]
CATALOG = [
    {
        "erp_product_id": 9,
        "name": "Трекер RT-Track",
        "unit": "шт",
        "price": {"amount": "1250000.00", "currency": "UZS"},
    }
]


class CrmTools(FakeTools):
    """crm-mcp: `create_service_request` отдаёт номер, как настоящий; `fail_request` — отказ."""

    def __init__(
        self, *, fail_request: bool = False, documents: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(lead(customer=True), kb(0.2))
        self.fail_request = fail_request
        self.documents = documents or []  # индекс документов CRM (docs-mcp)

    async def call(self, server: str, tool: str, args: dict[str, Any], context: str) -> Any:
        if tool == "search_documents":
            self.calls.append((server, tool, args))
            return self.documents
        if tool == "get_document_link":
            return {"document_id": args["document_id"], "title": "Счёт 77", "url": "http://docs/77"}
        if tool == "create_service_request":
            self.calls.append((server, tool, args))
            if self.fail_request:
                raise RuntimeError("crm-mcp down")
            return {"ok": True, "service_request_id": 77}
        return await super().call(server, tool, args, context)


def call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"c-{name}", name=name, arguments=arguments)


async def ask(
    text: str,
    model: ToolsModel,
    erp: FakeErp | None,
    *,
    tools: CrmTools | None = None,
    mode: str = "customer",
    scope: ErpScope | None = SCOPE,
) -> DialogResult:
    agent = DialogAgent(tools or CrmTools(), model, erp=erp)
    return await agent.run(
        lead_id=1,
        text=text,
        language="ru",
        context_token="t",
        settings=SETTINGS,
        mode=mode,
        erp_scope=scope,
    )


async def test_where_is_my_invoice_chains_deals_then_status() -> None:
    erp = FakeErp(list_client_deals=[DEAL], get_deal_status=STATUS)
    model = ToolsModel(
        reply("", call("list_client_deals")),
        reply("", call("get_deal_status", erp_deal_id=5)),
        reply("По данным системы счёт 77 на 12 500 000 сум выставлен."),
    )
    result = await ask("Где мой счёт?", model, erp)
    assert [(c[0], c[1]) for c in erp.calls] == [
        ("list_client_deals", {}),
        ("get_deal_status", {"erp_deal_id": 5}),
    ]
    assert all(c[2] == SCOPE for c in erp.calls)
    assert result.action == Action.ANSWER
    assert result.reply == "По данным системы счёт 77 на 12 500 000 сум выставлен."
    assert len(model.requests) == 3
    tool_message = model.requests[1][-1]
    assert tool_message["role"] == "tool"
    assert "Трекеры RT-Track" in tool_message["content"]


async def test_delivery_date_comes_only_from_erp() -> None:
    erp = FakeErp(get_delivery_status=DELIVERY)
    model = ToolsModel(
        reply("", call("get_delivery_status", erp_deal_id=5)),
        reply("Поставка ожидается 25 октября 2026 года."),
    )
    result = await ask("Когда поставка?", model, erp)
    assert result.reply == "Поставка ожидается 25 октября 2026 года."


async def test_invented_date_is_replaced_with_honest_fallback() -> None:
    erp = FakeErp(get_delivery_status=DELIVERY)
    model = ToolsModel(
        reply("", call("get_delivery_status", erp_deal_id=5)),
        reply("Поставка ожидается 30 октября."),
    )
    result = await ask("Когда поставка?", model, erp)
    assert result.reply == SETTINGS.texts.fallback.ru
    assert "30" not in (result.reply or "")


async def test_customer_gets_price_from_catalog() -> None:
    erp = FakeErp(search_catalog=CATALOG)
    model = ToolsModel(
        reply("", call("search_catalog", query="трекер")),
        reply("Трекер RT-Track стоит 1 250 000 сум за штуку."),
    )
    result = await ask("Сколько стоит трекер?", model, erp)
    assert result.reply == "Трекер RT-Track стоит 1 250 000 сум за штуку."


async def test_wrong_price_never_reaches_customer() -> None:
    erp = FakeErp(search_catalog=CATALOG)
    model = ToolsModel(
        reply("", call("search_catalog", query="трекер")),
        reply("Трекер стоит 990 000 сум."),
    )
    result = await ask("Сколько стоит трекер?", model, erp)
    assert result.reply == SETTINGS.texts.fallback.ru


async def test_lead_gets_no_erp_tools_and_cannot_call_them() -> None:
    erp = FakeErp(search_catalog=CATALOG)
    tools = CrmTools()
    tools.lead, tools.kb = lead(customer=False), kb(0.8)
    model = ToolsModel(
        reply("", call("search_catalog", query="трекер")),
        reply("Точную стоимость рассчитает менеджер."),
    )
    result = await ask(
        "Сколько стоит трекер?", model, erp, tools=tools, mode="prospect", scope=None
    )
    assert not model.offered[0] & ERP_TOOL_NAMES
    assert erp.calls == []  # даже вызов, который модель придумала сама, до ERP не доходит
    assert result.reply == "Точную стоимость рассчитает менеджер."


async def test_lead_with_scope_still_gets_no_erp() -> None:
    erp = FakeErp(search_catalog=CATALOG)
    tools = CrmTools()
    tools.lead, tools.kb = lead(customer=False), kb(0.8)
    model = ToolsModel(reply("Цену называет менеджер."))
    await ask("Сколько стоит трекер?", model, erp, tools=tools, mode="prospect", scope=SCOPE)
    assert not model.offered[0] & ERP_TOOL_NAMES
    assert erp.calls == []


async def test_customer_without_erp_company_gets_no_erp_tools() -> None:
    erp = FakeErp()
    model = ToolsModel(reply("Передаю менеджеру."))
    await ask("Когда поставка?", model, erp, scope=None)
    assert not model.offered[0] & ERP_TOOL_NAMES


async def test_customer_gets_exactly_the_service_tools() -> None:
    model = ToolsModel(reply("Здравствуйте!"))
    await ask("Что с заказом?", model, FakeErp())
    assert model.offered[0] == ERP_TOOL_NAMES | {"request_callback", "create_service_request"}
    assert "get_document_link" not in model.offered[0]
    assert "create_request" not in model.offered[0]


async def test_ids_from_the_model_never_reach_erp() -> None:
    erp = FakeErp(get_deal_status=STATUS)
    forged = call(
        "get_deal_status", erp_deal_id=5, erp_company_id=999, crm_client_id=1, company="Бета"
    )
    model = ToolsModel(reply("", forged), reply("Счёт 77 выставлен."))
    await ask("Покажи счёт компании Бета", model, erp)
    ((_, args, scope),) = erp.calls
    assert args == {"erp_deal_id": 5}
    assert scope == SCOPE


async def test_erp_unavailable_is_honest_and_hands_over_to_manager() -> None:
    erp = FakeErp()
    erp.failure = ErpMcpError("unavailable", "list_client_deals")
    tools = CrmTools()
    model = ToolsModel(
        reply("", call("list_client_deals")),
        reply("Сейчас не могу это проверить."),
    )
    result = await ask("Где мой счёт?", model, erp, tools=tools)
    assert result.service_request is True
    assert tools.calls[-1][:2] == ("crm", "create_service_request")
    assert "Где мой счёт?" in tools.calls[-1][2]["summary"]
    assert result.reply is not None
    assert result.reply.startswith("Сейчас не могу это проверить.")
    assert "77" in result.reply  # номер запроса из crm-mcp — «Запрос №77»
    tool_output = model.requests[1][-1]["content"]
    assert "erp_unavailable" in tool_output
    assert '"ok": false' in tool_output
    assert len(model.requests) == 2  # после отказа ERP новых кругов нет


@pytest.mark.parametrize(
    "kind", ["unavailable", "rate_limited", "context_rejected", "invalid_arguments", "tool_error"]
)
async def test_every_erp_failure_kind_gives_the_same_honest_answer(kind: str) -> None:
    erp = FakeErp()
    erp.failure = ErpMcpError(kind, "get_deal_status")  # type: ignore[arg-type]
    model = ToolsModel(
        reply("", call("get_deal_status", erp_deal_id=5)),
        reply("Сейчас не могу проверить."),
    )
    result = await ask("Что со сделкой?", model, erp)
    assert result.service_request is True
    assert (result.reply or "").startswith("Сейчас не могу проверить.")


async def test_numbers_after_erp_failure_are_dropped() -> None:
    erp = FakeErp()
    erp.failure = ErpMcpError("unavailable", "get_delivery_status")
    model = ToolsModel(
        reply("", call("get_delivery_status", erp_deal_id=5)),
        reply("Обычно это занимает 3 дня, ориентируйтесь на 25 октября."),
    )
    result = await ask("Когда поставка?", model, erp)
    assert result.reply is not None
    assert result.reply.startswith(SETTINGS.texts.fallback.ru)
    assert "25" not in result.reply
    assert "3 дня" not in result.reply


async def test_failed_handover_does_not_promise_a_manager() -> None:
    erp = FakeErp()
    erp.failure = ErpMcpError("unavailable", "list_client_deals")
    model = ToolsModel(
        reply("", call("list_client_deals")),
        reply("Я передал вопрос менеджеру."),
    )
    result = await ask("Где мой счёт?", model, erp, tools=CrmTools(fail_request=True))
    assert result.service_request is False
    assert result.reply == SETTINGS.texts.fallback.ru


async def test_empty_erp_result_is_passed_to_the_model_as_empty() -> None:
    erp = FakeErp(get_deal_status=None)
    model = ToolsModel(
        reply("", call("get_deal_status", erp_deal_id=999)),
        reply("По вашим данным в системе этого не нашёл."),
    )
    result = await ask("Что со сделкой 999?", model, erp)
    assert '"result": null' in model.requests[1][-1]["content"]
    assert result.service_request is False  # пусто — не отказ: ERP ответил


async def test_tool_rounds_are_bounded() -> None:
    erp = FakeErp(list_client_deals=[DEAL])
    model = ToolsModel(*[reply("", call("list_client_deals"))] * 3, reply("Вот сделка D-5."))
    result = await ask("Что у меня?", model, erp)
    assert len(erp.calls) == 3
    assert model.offered[-1] == set()  # последний ответ — без инструментов
    assert result.reply == "Вот сделка D-5."


async def test_invoice_found_in_crm_index_is_delivered_without_asking_erp() -> None:
    erp = FakeErp()
    invoice = {"document_id": 3, "title": "Счёт 77", "type": "invoice", "number": "77"}
    tools = CrmTools(documents=[invoice])
    result = await ask("Где мой счёт?", ToolsModel(), erp, tools=tools)
    assert result.action == Action.DELIVER_DOCUMENT
    assert erp.calls == []


async def test_missing_document_asks_erp_instead_of_handing_over() -> None:
    erp = FakeErp(list_client_documents=[])
    model = ToolsModel(
        reply("", call("list_client_documents", kind="contract")),
        reply("Договора в системе по вашим данным не нашёл. Позвать менеджера?"),
    )
    result = await ask("Пришлите договор", model, erp)
    assert result.action == Action.ANSWER
    assert result.reason == "document_lookup_erp"
    assert erp.calls[0][:2] == ("list_client_documents", {"kind": "contract"})


async def test_missing_document_without_erp_still_goes_to_manager() -> None:
    result = await ask("Пришлите договор", ToolsModel(), None, scope=None)
    assert result.action == Action.HANDOFF
    assert result.reason == "document_not_found"


async def test_tool_calls_in_a_tool_less_completion_are_not_executed() -> None:
    erp = FakeErp(list_client_deals=[DEAL])
    model = ToolsModel(
        reply("", call("list_client_deals")),
        reply("Вот сделка.", call("list_client_deals")),  # итоговый ответ без инструментов
    )
    erp.failure = ErpMcpError("unavailable", "list_client_deals")
    await ask("Что у меня?", model, erp)
    assert len(erp.calls) == 1
