"""Инструменты ERP, которые видит модель, не расходятся с `packages/contracts/mcp-tools.json`."""

import json
from typing import Any

from app.agents.dialog.erp_tools import ERP_TOOL_NAMES, ERP_TOOLS, clean_args
from tests.unit.agents.fake_erp_mcp import CONTRACT

CONTRACT_TOOLS = {t["name"]: t for t in json.loads(CONTRACT.read_text(encoding="utf-8"))["tools"]}
# Сознательно не отданы модели (см. docstring erp_tools): файл отправляет код, запрос оформляет CRM.
WITHHELD = {"get_document_link", "create_request"}


def test_every_exposed_tool_exists_in_the_contract_with_the_same_schema() -> None:
    assert set(CONTRACT_TOOLS) >= ERP_TOOL_NAMES
    for tool in ERP_TOOLS:
        function: dict[str, Any] = tool["function"]
        spec = CONTRACT_TOOLS[function["name"]]
        assert function["parameters"] == spec["input_schema"], function["name"]
        assert "customer" in spec["modes"], function["name"]


def test_withheld_tools_are_exactly_the_rest_of_the_contract() -> None:
    assert set(CONTRACT_TOOLS) - ERP_TOOL_NAMES == WITHHELD


def test_no_exposed_tool_takes_client_or_company_identifiers() -> None:
    forbidden = {"erp_company_id", "crm_client_id", "company_id", "client_id", "lead_id"}
    for tool in ERP_TOOLS:
        assert not forbidden & set(tool["function"]["parameters"]["properties"])


def test_clean_args_keeps_only_schema_properties() -> None:
    assert clean_args("search_catalog", {"query": "x", "top_k": 3, "erp_company_id": 9}) == {
        "query": "x",
        "top_k": 3,
    }
    assert clean_args("list_client_deals", {"erp_company_id": 9}) == {}
    assert clean_args("unknown_tool", {"a": 1}) == {}
